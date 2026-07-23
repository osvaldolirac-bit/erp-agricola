"""Bitácora informativa de salidas de petróleo (QR, sin afectar stock ERP)."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from flask import current_app, request

from demo_web.services.demo_loader import get_demo_module, get_erp_app

_CODIGO_RE = re.compile(r"^PET-(\d+)$", re.I)


def _conn() -> sqlite3.Connection:
    demo = get_demo_module()
    return demo.conectar_db()


def formatear_codigo_pet(n: int) -> str:
    if n < 100:
        return f"PET-{n:02d}"
    return f"PET-{n}"


def _max_numero_codigo(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT codigo FROM petroleo_bitacora WHERE codigo IS NOT NULL AND codigo != ''"
    ).fetchall()
    max_n = 0
    for (cod,) in rows:
        m = _CODIGO_RE.match(str(cod).strip())
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _siguiente_codigo(conn: sqlite3.Connection) -> str:
    return formatear_codigo_pet(_max_numero_codigo(conn) + 1)


def _retrofill_codigos(conn: sqlite3.Connection) -> None:
    pendientes = conn.execute(
        """SELECT id FROM petroleo_bitacora
           WHERE codigo IS NULL OR TRIM(codigo) = ''
           ORDER BY id"""
    ).fetchall()
    if not pendientes:
        return
    n = _max_numero_codigo(conn)
    for (rid,) in pendientes:
        n += 1
        conn.execute(
            "UPDATE petroleo_bitacora SET codigo=? WHERE id=?",
            (formatear_codigo_pet(n), rid),
        )


def normalizar_cuarteles(cuarteles: list[str]) -> str:
    demo = get_demo_module()
    canon = {c.upper(): c for c in getattr(demo, "CENTROS_COSTO", []) or []}
    orden = {c.upper(): i for i, c in enumerate(getattr(demo, "CENTROS_COSTO", []) or [])}
    vals = {c.strip().upper() for c in cuarteles if c and c.strip()}
    ordenados = sorted(vals, key=lambda v: (orden.get(v, 999), v))
    return ", ".join(canon.get(v, v) for v in ordenados)


TIPOS_MAQUINARIA_BITACORA = ("Tractor", "Camión", "Vehículo")


def maquinaria_para_formulario() -> list[dict[str, str]]:
    """Equipos activos de la maestra: tractores, camiones y vehículos."""
    from erp_maquinaria import etiqueta_maquinaria, listar_maquinaria

    orden_tipo = {"Tractor": 0, "Camión": 1, "Vehículo": 2}
    conn = _conn()
    try:
        items = listar_maquinaria(conn, solo_activos=True, tipos=TIPOS_MAQUINARIA_BITACORA)
        items.sort(key=lambda m: (orden_tipo.get(m["tipo"], 9), m.get("orden", 0), m["codigo"]))
        return [
            {
                "codigo": m["codigo"],
                "etiqueta": etiqueta_maquinaria(m["codigo"], m["nombre"]),
                "tipo": m["tipo"],
            }
            for m in items
        ]
    finally:
        conn.close()


def cuarteles_para_formulario() -> list[str]:
    """Centros de costo en orden maestro ERP (OTROS al final)."""
    demo = get_demo_module()
    raw = list(getattr(demo, "CENTROS_COSTO", []) or [])
    otros = [c for c in raw if str(c).strip().upper() == "OTROS"]
    resto = [c for c in raw if str(c).strip().upper() != "OTROS"]
    return resto + otros


def _migrar_personal_autorizado(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(personal)").fetchall()}
    if "autorizado_salida_petroleo" not in cols:
        conn.execute(
            "ALTER TABLE personal ADD COLUMN autorizado_salida_petroleo INTEGER DEFAULT 0"
        )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autorizados_salida_petroleo_extra (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nombre TEXT NOT NULL UNIQUE,
               activo INTEGER DEFAULT 1,
               fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
           )"""
    )


def responsables_autorizados_para_formulario() -> list[dict[str, str]]:
    """Trabajadores autorizados + dueños/extras activos para el QR de salida."""
    conn = _conn()
    try:
        _migrar_personal_autorizado(conn)
        conn.commit()
        out: list[dict[str, str]] = []
        rows = conn.execute(
            """SELECT id, nombre FROM personal
               WHERE COALESCE(estado, 'Activo') = 'Activo'
                 AND COALESCE(autorizado_salida_petroleo, 0) = 1
               ORDER BY nombre"""
        ).fetchall()
        for rid, nombre in rows:
            out.append({"id": f"p-{rid}", "nombre": str(nombre)})
        extras = conn.execute(
            """SELECT id, nombre FROM autorizados_salida_petroleo_extra
               WHERE COALESCE(activo, 1) = 1
               ORDER BY nombre"""
        ).fetchall()
        for eid, nombre in extras:
            out.append({"id": f"e-{eid}", "nombre": str(nombre)})
        out.sort(key=lambda x: x["nombre"].casefold())
        return out
    finally:
        conn.close()


def migrar_tabla(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = _conn()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS petroleo_bitacora (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT UNIQUE,
                   fecha_hora TEXT NOT NULL,
                   litros REAL NOT NULL,
                   maquinaria TEXT NOT NULL,
                   responsable TEXT NOT NULL,
                   huerto TEXT DEFAULT '',
                   ip_origen TEXT,
                   creado_en TEXT NOT NULL
               )"""
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo_bitacora)").fetchall()}
        if "huerto" not in cols:
            conn.execute("ALTER TABLE petroleo_bitacora ADD COLUMN huerto TEXT DEFAULT ''")
        if "codigo" not in cols:
            conn.execute("ALTER TABLE petroleo_bitacora ADD COLUMN codigo TEXT")
        _migrar_personal_autorizado(conn)
        row = conn.execute(
            "SELECT valor FROM schema_meta WHERE clave='salida_petroleo_token_v1'"
        ).fetchone()
        if not row:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT INTO schema_meta (clave, valor) VALUES ('salida_petroleo_token_v1', ?)",
                (token,),
            )
        _retrofill_codigos(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def _token_db(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave='salida_petroleo_token_v1'"
    ).fetchone()
    return str(row[0]).strip() if row and row[0] else None


def obtener_token() -> str:
    conn = _conn()
    try:
        migrar_tabla(conn)
        token = _token_db(conn)
        if not token:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES ('salida_petroleo_token_v1', ?)",
                (token,),
            )
            conn.commit()
        return token
    finally:
        conn.close()


def token_valido(recibido: str | None) -> bool:
    if not recibido or not recibido.strip():
        return False
    conn = _conn()
    try:
        esperado = _token_db(conn)
        if not esperado:
            return False
        return secrets.compare_digest(recibido.strip(), esperado)
    finally:
        conn.close()


def url_publica(token: str | None = None) -> str:
    tok = token or obtener_token()
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/laconcepcion").rstrip("/")
    return f"{base}{prefix}/salida-petroleo?t={tok}"


def _destinatario_alerta() -> list[str]:
    demo = get_demo_module()
    dest: list[str] = []
    if hasattr(demo, "obtener_destinatarios_petroleo_bitacora"):
        conn = demo.conectar_db()
        try:
            dest = list(demo.obtener_destinatarios_petroleo_bitacora(conn))
        finally:
            conn.close()
    if dest:
        return dest
    conf = demo._conf_smtp_prod() if hasattr(demo, "_conf_smtp_prod") else None
    if conf and conf.get("receptor_admin"):
        return [str(conf["receptor_admin"]).strip()]
    return []


def buscar_duplicado_reciente(
    conn: sqlite3.Connection,
    litros: float,
    huerto: str,
    maquinaria: str,
    responsable: str,
    minutos: int = 10,
) -> str | None:
    demo = get_demo_module()
    desde = (demo.hora_chile() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """SELECT codigo FROM petroleo_bitacora
           WHERE fecha_hora >= ?
             AND ABS(litros - ?) < 0.01
             AND UPPER(TRIM(huerto)) = ?
             AND UPPER(TRIM(maquinaria)) = ?
             AND UPPER(TRIM(responsable)) = ?
             AND codigo IS NOT NULL AND TRIM(codigo) != ''
           ORDER BY id DESC LIMIT 1""",
        (
            desde,
            litros,
            huerto.strip().upper(),
            maquinaria.strip().upper(),
            responsable.strip().upper(),
        ),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def enviar_alerta(registro: dict[str, Any]) -> bool:
    demo = get_demo_module()
    if not hasattr(demo, "_enviar_correo_html"):
        return False
    from erp_correo_html import html_esc, plantilla_correo_html

    dest = _destinatario_alerta()
    if not dest:
        return False
    codigo = registro.get("codigo", "")
    interior = f"""
        <p style="color:#1F2933;line-height:1.55;margin:0 0 12px;">
          Se registró una salida de petróleo desde la <b>bitácora de campo</b> (informativa).
          Debe imputarla manualmente en el ERP cuando corresponda.
        </p>
        <div style="background:#FFF3E0;border:1px solid #FFCC80;border-radius:10px;padding:16px 18px;">
          <p style="margin:6px 0;"><b>Código:</b> {html_esc(codigo)}</p>
          <p style="margin:6px 0;"><b>Fecha/hora:</b> {html_esc(registro.get('fecha_hora', ''))}</p>
          <p style="margin:6px 0;"><b>Litros:</b> {html_esc(registro.get('litros_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>Cuarteles:</b> {html_esc(registro.get('huerto', ''))}</p>
          <p style="margin:6px 0;"><b>Maquinaria:</b> {html_esc(registro.get('maquinaria', ''))}</p>
          <p style="margin:6px 0;"><b>Responsable:</b> {html_esc(registro.get('responsable', ''))}</p>
        </div>
    """
    cuerpo = plantilla_correo_html(
        "vencimiento",
        f"⛽ {codigo} — Salida petróleo bitácora",
        interior,
        nombre_erp="ERP La Concepción",
        pie="Registro informativo vía QR. No descuenta stock del estanque.",
    )
    asunto = (
        f"⛽ {codigo} | {registro.get('litros_fmt', '')} L | "
        f"{registro.get('maquinaria', '')[:25]} | {registro.get('responsable', '')[:20]}"
    )
    return bool(demo._enviar_correo_html(asunto, cuerpo, dest))


def registrar_salida(
    litros: float,
    cuarteles: list[str],
    maquinaria: str,
    responsable: str,
    *,
    confirmar_duplicado: bool = False,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto = normalizar_cuarteles(cuarteles)
    maquinaria = maquinaria.strip()
    responsable = responsable.strip()
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()

    conn = _conn()
    try:
        migrar_tabla(conn)
        if not confirmar_duplicado:
            dup = buscar_duplicado_reciente(conn, litros, huerto, maquinaria, responsable)
            if dup:
                return {
                    "ok": False,
                    "duplicado": True,
                    "codigo_duplicado": dup,
                    "msg": f"Ya existe {dup} con los mismos datos (últimos 10 min).",
                }
        codigo = _siguiente_codigo(conn)
        conn.execute(
            """INSERT INTO petroleo_bitacora
               (codigo, fecha_hora, litros, huerto, maquinaria, responsable, ip_origen, creado_en)
               VALUES (?,?,?,?,?,?,?,?)""",
            (codigo, fh, litros, huerto, maquinaria, responsable, ip or None, fh),
        )
        conn.commit()
    finally:
        conn.close()

    registro = {
        "codigo": codigo,
        "fecha_hora": fh,
        "litros": litros,
        "litros_fmt": demo.f_decimal(litros),
        "huerto": huerto,
        "maquinaria": maquinaria,
        "responsable": responsable,
    }
    mail_ok = enviar_alerta(registro)
    try:
        conn = _conn()
        det = (
            f"Marcha blanca | {codigo} | {registro['litros_fmt']} L | {huerto[:40]} | "
            f"{maquinaria[:60]} | {responsable[:40]}"
            + (" | mail OK" if mail_ok else " | mail falló")
        )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            ("BITACORA-PETROLEO", "PETROLEO CAMPO", det, fh),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"ok": True, "mail_ok": mail_ok, **registro}


def listar_registros(conn, limite: int = 50) -> list[dict[str, Any]]:
    """Últimos registros de bitácora campo (solo lectura, ERP)."""
    demo = get_demo_module()
    migrar_tabla(conn)
    rows = conn.execute(
        """SELECT codigo, fecha_hora, litros, huerto, maquinaria, responsable
           FROM petroleo_bitacora
           ORDER BY id DESC
           LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for codigo, fh, litros, huerto, maquinaria, responsable in rows:
        out.append(
            {
                "codigo": codigo or "—",
                "fecha_hora": fh,
                "litros": demo.f_decimal(litros),
                "huerto": huerto or "—",
                "maquinaria": maquinaria,
                "responsable": responsable,
            }
        )
    return out


def datos_compartir() -> dict[str, str]:
    """URL pública + metadatos para QR / compartir (requiere app context)."""
    migrar_tabla()
    tok = obtener_token()
    return {"url": url_publica(tok), "token": tok}


def habilitado() -> bool:
    return get_erp_app() == "concepcion"
