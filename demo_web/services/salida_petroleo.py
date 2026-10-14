"""Bitácora informativa de salidas de petróleo (link personal, sin afectar stock ERP)."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from flask import current_app, request

from demo_web.services.demo_loader import get_demo_module, get_erp_app
from demo_web.services.tenant_scope import centros_costo

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
    canon = {c.upper(): c for c in centros_costo(demo) or []}
    orden = {c.upper(): i for i, c in enumerate(centros_costo(demo) or [])}
    vals = {c.strip().upper() for c in cuarteles if c and c.strip()}
    ordenados = sorted(vals, key=lambda v: (orden.get(v, 999), v))
    return ", ".join(canon.get(v, v) for v in ordenados)


# Misma maestra / mismos tipos que el módulo Petróleo (incluye Otro, Motobomba, etc.).
# Antes solo Tractor/Camión/Vehículo: equipos nuevos (p.ej. sala de riego) no aparecían en el QR.


def maquinaria_para_formulario() -> list[dict[str, str]]:
    """Equipos activos de la maestra (todos los tipos usados en Petróleo)."""
    from erp_maquinaria import (
        TIPOS_MAQUINARIA_PETROLEO,
        etiqueta_maquinaria,
        listar_maquinaria,
    )

    orden_tipo = {t: i for i, t in enumerate(TIPOS_MAQUINARIA_PETROLEO)}
    conn = _conn()
    try:
        items = listar_maquinaria(
            conn, solo_activos=True, tipos=list(TIPOS_MAQUINARIA_PETROLEO)
        )
        items.sort(
            key=lambda m: (
                orden_tipo.get(m["tipo"], 99),
                m.get("orden", 0),
                m["codigo"],
            )
        )
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


def saldo_estanque_para_formulario() -> dict[str, Any]:
    """Saldo actual del estanque (mismas reglas que el módulo Petróleo)."""
    demo = get_demo_module()
    conn = _conn()
    try:
        fn = getattr(demo, "_petroleo_saldo_estanque", None)
        if callable(fn):
            litros_saldo, _costo = fn(conn)
            saldo = float(litros_saldo or 0)
        else:
            row_c = conn.execute(
                "SELECT COALESCE(SUM(litros),0) FROM petroleo "
                "WHERE tipo='Carga' OR (tipo='Ajuste Manual' AND litros > 0)"
            ).fetchone()
            row_s = conn.execute(
                "SELECT COALESCE(SUM(litros),0) FROM petroleo "
                "WHERE tipo='Salida' OR (tipo='Ajuste Manual' AND litros < 0)"
            ).fetchone()
            tot_c = float(row_c[0] or 0)
            tot_s = abs(float(row_s[0] or 0))
            saldo = tot_c - tot_s
        fmt = demo.f_decimal(saldo) if hasattr(demo, "f_decimal") else f"{saldo:.1f}"
        return {"litros": saldo, "fmt": fmt}
    except Exception:
        return {"litros": 0.0, "fmt": "0"}
    finally:
        conn.close()


def cuarteles_para_formulario() -> list[str]:
    """Centros de costo en orden maestro ERP (OTROS al final)."""
    demo = get_demo_module()
    raw = list(centros_costo(demo) or [])
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
    """Trabajadores autorizados + dueños/extras activos para Salida Link."""
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


# Cookie en el teléfono del operador (formulario Salida Link sin login ERP).
_COOKIE_OP_MAX_AGE = 180 * 24 * 3600  # 180 días


def cookie_nombre_operador() -> str:
    app = get_erp_app() or "erp"
    return f"erp_sp_op_{app}"


def cookie_path_operador() -> str:
    """Path del cookie. '/' es seguro detrás de nginx (nombres distintos por ERP_APP)."""
    return "/"


def resolver_responsable_por_id(
    op_id: str | None,
    responsables: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    """Valida id p-N / e-N contra la lista autorizada vigente."""
    key = (op_id or "").strip()
    if not key:
        return None
    opts = responsables if responsables is not None else responsables_autorizados_para_formulario()
    for r in opts:
        if r.get("id") == key:
            return {"id": r["id"], "nombre": r["nombre"]}
    return None


def leer_operador_cookie(
    responsables: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    return resolver_responsable_por_id(
        request.cookies.get(cookie_nombre_operador()),
        responsables,
    )


def aplicar_cookie_operador(response, op_id: str) -> None:
    """Persiste el operador en el navegador/teléfono del campo."""
    if not op_id:
        return
    response.set_cookie(
        cookie_nombre_operador(),
        op_id,
        max_age=_COOKIE_OP_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=bool(request.is_secure),
        path=cookie_path_operador(),
    )


def borrar_cookie_operador(response) -> None:
    response.set_cookie(
        cookie_nombre_operador(),
        "",
        max_age=0,
        expires=0,
        httponly=True,
        samesite="Lax",
        secure=bool(request.is_secure),
        path=cookie_path_operador(),
    )


def migrar_tabla(conn: sqlite3.Connection | None = None) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    own = conn is None
    if own:
        conn = _conn()
    try:
        if conn_en_solo_lectura(conn):
            return
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
        if "maquinaria_codigo" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN maquinaria_codigo TEXT DEFAULT ''"
            )
        if "estado" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN estado TEXT DEFAULT 'pendiente'"
            )
            conn.execute(
                "UPDATE petroleo_bitacora SET estado='pendiente' WHERE estado IS NULL OR TRIM(estado)=''"
            )
        if "autorizado_por" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN autorizado_por TEXT DEFAULT ''"
            )
        if "autorizado_en" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN autorizado_en TEXT DEFAULT ''"
            )
        if "rechazado_por" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazado_por TEXT DEFAULT ''"
            )
        if "rechazado_en" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazado_en TEXT DEFAULT ''"
            )
        if "rechazo_motivo" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazo_motivo TEXT DEFAULT ''"
            )
        # Enlace bitácora → filas reales de petroleo (historial / costos)
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo)").fetchall()}
        if "bitacora_codigo" not in pcols:
            conn.execute(
                "ALTER TABLE petroleo ADD COLUMN bitacora_codigo TEXT DEFAULT ''"
            )
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


def url_publica(token: str | None = None, op: str | None = None) -> str:
    """URL del formulario Salida Link. Si `op` es p-N / e-N, fija el operador (link personal)."""
    from urllib.parse import quote

    tok = token or obtener_token()
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/laconcepcion").rstrip("/")
    url = f"{base}{prefix}/salida-petroleo?t={tok}"
    op_id = (op or "").strip()
    if op_id:
        url += f"&op={quote(op_id, safe='')}"
    return url


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
    minutos: int = 1,
    maquinaria_codigo: str = "",
) -> str | None:
    """Misma config litros+equipo+cuartel+usuario dentro de N minutos."""
    demo = get_demo_module()
    desde = (demo.hora_chile() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    maq_cod = (maquinaria_codigo or "").strip().upper()
    if maq_cod:
        row = conn.execute(
            """SELECT codigo FROM petroleo_bitacora
               WHERE fecha_hora >= ?
                 AND ABS(litros - ?) < 0.01
                 AND UPPER(TRIM(huerto)) = ?
                 AND (
                   UPPER(TRIM(COALESCE(maquinaria_codigo, ''))) = ?
                   OR UPPER(TRIM(maquinaria)) = ?
                 )
                 AND UPPER(TRIM(responsable)) = ?
                 AND codigo IS NOT NULL AND TRIM(codigo) != ''
                 AND LOWER(COALESCE(estado, 'pendiente')) != 'rechazado'
               ORDER BY id DESC LIMIT 1""",
            (
                desde,
                litros,
                huerto.strip().upper(),
                maq_cod,
                maquinaria.strip().upper(),
                responsable.strip().upper(),
            ),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT codigo FROM petroleo_bitacora
               WHERE fecha_hora >= ?
                 AND ABS(litros - ?) < 0.01
                 AND UPPER(TRIM(huerto)) = ?
                 AND UPPER(TRIM(maquinaria)) = ?
                 AND UPPER(TRIM(responsable)) = ?
                 AND codigo IS NOT NULL AND TRIM(codigo) != ''
                 AND LOWER(COALESCE(estado, 'pendiente')) != 'rechazado'
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
          Se registró una salida de petróleo desde <b>Salida Link</b> (informativa).
          Un administrador debe <b>autorizarla</b> en Petróleo → Salida Link para imputarla al estanque.
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
        f"⛽ {codigo} — Salida Link petróleo",
        interior,
        nombre_erp=_nombre_erp(),
        pie="Registro informativo vía link personal. No descuenta stock del estanque.",
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
    maquinaria_codigo: str = "",
    confirmar_duplicado: bool = False,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto = normalizar_cuarteles(cuarteles)
    maquinaria = maquinaria.strip()
    maquinaria_codigo = (maquinaria_codigo or "").strip()
    responsable = responsable.strip()
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()

    conn = _conn()
    try:
        migrar_tabla(conn)
        # BEGIN IMMEDIATE: evita carrera entre workers gunicorn (doble tap).
        try:
            conn.commit()
        except Exception:
            pass
        conn.execute("BEGIN IMMEDIATE")
        # Hard-block 1 min: ignora confirmar_duplicado (no se puede repetir la misma config).
        dup = buscar_duplicado_reciente(
            conn,
            litros,
            huerto,
            maquinaria,
            responsable,
            minutos=1,
            maquinaria_codigo=maquinaria_codigo,
        )
        if dup:
            conn.rollback()
            return {
                "ok": False,
                "duplicado": True,
                "codigo_duplicado": dup,
                "msg": (
                    f"Ya registró {dup} con los mismos litros, equipo, cuartel(es) "
                    f"y responsable hace menos de 1 minuto. Espere un momento."
                ),
            }
        codigo = _siguiente_codigo(conn)
        conn.execute(
            """INSERT INTO petroleo_bitacora
               (codigo, fecha_hora, litros, huerto, maquinaria, maquinaria_codigo,
                responsable, ip_origen, creado_en, estado)
               VALUES (?,?,?,?,?,?,?,?,?,'pendiente')""",
            (
                codigo,
                fh,
                litros,
                huerto,
                maquinaria,
                maquinaria_codigo,
                responsable,
                ip or None,
                fh,
            ),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
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
            f"Campo | {codigo} | {registro['litros_fmt']} L | {huerto[:40]} | "
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


def _cuarteles_desde_huerto(huerto: str) -> list[str]:
    demo = get_demo_module()
    canon = {c.upper(): c for c in centros_costo(demo) or []}
    out = []
    for part in str(huerto or "").split(","):
        key = part.strip().upper()
        if not key:
            continue
        if key in canon:
            out.append(canon[key])
    return out


def _resolver_codigo_maquinaria(conn, codigo: str, etiqueta: str) -> str:
    from erp_maquinaria import mapear_legacy_a_codigo

    cod = (codigo or "").strip()
    if cod:
        return cod
    return mapear_legacy_a_codigo(conn, etiqueta) or (etiqueta or "").strip()


def enviar_alerta_autorizacion(registro: dict[str, Any], usuario: str) -> bool:
    demo = get_demo_module()
    if not hasattr(demo, "_enviar_correo_html"):
        return False
    from erp_correo_html import html_esc, plantilla_correo_html

    dest = _destinatario_alerta()
    if not dest:
        return False
    codigo = registro.get("codigo", "")
    detalle_cc = registro.get("detalle_cc_html", "")
    interior = f"""
        <p style="color:#1F2933;line-height:1.55;margin:0 0 12px;">
          Se <b>autorizó</b> la Salida Link <b>{html_esc(codigo)}</b> y quedó
          imputada al estanque ERP / centros de costo.
        </p>
        <div style="background:#E8F5E9;border:1px solid #A5D6A7;border-radius:10px;padding:16px 18px;">
          <p style="margin:6px 0;"><b>Código:</b> {html_esc(codigo)}</p>
          <p style="margin:6px 0;"><b>Autorizado por:</b> {html_esc(usuario)}</p>
          <p style="margin:6px 0;"><b>Fecha/hora campo:</b> {html_esc(registro.get('fecha_hora', ''))}</p>
          <p style="margin:6px 0;"><b>Litros:</b> {html_esc(registro.get('litros_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>Cuarteles:</b> {html_esc(registro.get('huerto', ''))}</p>
          <p style="margin:6px 0;"><b>Maquinaria:</b> {html_esc(registro.get('maquinaria', ''))}</p>
          <p style="margin:6px 0;"><b>Responsable:</b> {html_esc(registro.get('responsable', ''))}</p>
          <p style="margin:6px 0;"><b>PMP neto:</b> ${html_esc(registro.get('pmp_fmt', '0'))}/L</p>
          {detalle_cc}
        </div>
    """
    cuerpo = plantilla_correo_html(
        "vencimiento",
        f"✅ {codigo} — Autorización salida petróleo",
        interior,
        nombre_erp=_nombre_erp(),
        pie="Salida autorizada e imputada al estanque / historial de Petróleo.",
    )
    asunto = (
        f"✅ {codigo} autorizado | {registro.get('litros_fmt', '')} L | "
        f"{registro.get('maquinaria', '')[:25]}"
    )
    return bool(demo._enviar_correo_html(asunto, cuerpo, dest))


def autorizar_salida(codigo: str, usuario: str) -> dict[str, Any]:
    """Imputa bitácora pendiente al estanque (PMP + prorrateo Administración)."""
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        row = conn.execute(
            """SELECT id, codigo, fecha_hora, litros, huerto, maquinaria, maquinaria_codigo,
                      responsable, COALESCE(estado, 'pendiente')
               FROM petroleo_bitacora WHERE codigo=?""",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        (
            _bid,
            codigo,
            fecha_hora,
            litros,
            huerto,
            maquinaria,
            maquinaria_codigo,
            responsable,
            estado,
        ) = row
        est = str(estado or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} está rechazado; no se puede autorizar."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente (estado: {estado})."}

        litros = float(litros or 0)
        if litros <= 0:
            return {"ok": False, "msg": "Litros inválidos en la Salida Link."}

        cuarteles = _cuarteles_desde_huerto(huerto)
        if not cuarteles:
            return {"ok": False, "msg": "No se pudieron resolver los cuarteles de la Salida Link."}

        # La Concepción: prorrateo Administración. DEMO: partes iguales (como Salida manual).
        if hasattr(demo, "_reparto_por_cc"):
            reparto, err_cc = demo._reparto_por_cc(conn, litros, cuarteles)
            if err_cc:
                return {"ok": False, "msg": err_cc}
        else:
            parte = litros / len(cuarteles)
            reparto = [(c, parte) for c in cuarteles]

        try:
            pmp = float(demo._petroleo_pmp_neto(conn) or 0)
        except Exception:
            pmp = 0.0

        vehiculo = _resolver_codigo_maquinaria(conn, maquinaria_codigo or "", maquinaria or "")
        if not vehiculo:
            return {"ok": False, "msg": "No se pudo resolver el equipo/maquinaria."}

        fecha_salida = str(fecha_hora or "")[:10]
        if len(fecha_salida) < 10:
            fecha_salida = str(demo.hoy)

        lineas = []
        for cc, litros_cc in reparto:
            valor = float(litros_cc) * pmp
            conn.execute(
                """INSERT INTO petroleo
                   (tipo, litros, vehiculo, responsable, centro_costo, fecha,
                    valor_imputado, bitacora_codigo)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "Salida",
                    float(litros_cc),
                    vehiculo,
                    responsable,
                    str(cc).upper(),
                    fecha_salida,
                    valor,
                    codigo,
                ),
            )
            lineas.append((cc, float(litros_cc), valor))

        fh_auth = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE petroleo_bitacora
               SET estado='autorizado', autorizado_por=?, autorizado_en=?
               WHERE codigo=?""",
            (usuario, fh_auth, codigo),
        )
        det_cc = ", ".join(f"{c}:{demo.f_decimal(l)}L" for c, l, _ in lineas)
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                usuario,
                "PETROLEO AUTORIZAR",
                f"{codigo} | {demo.f_decimal(litros)} L | {det_cc[:120]} | {vehiculo}",
                fh_auth,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    from erp_correo_html import html_esc

    filas_cc = "".join(
        f"<p style='margin:4px 0;'>{html_esc(cc)}: {html_esc(demo.f_decimal(l))} L · "
        f"${html_esc(demo.f_puntos(v))}</p>"
        for cc, l, v in lineas
    )
    registro = {
        "codigo": codigo,
        "fecha_hora": fecha_hora,
        "litros_fmt": demo.f_decimal(litros),
        "huerto": huerto,
        "maquinaria": maquinaria,
        "responsable": responsable,
        "pmp_fmt": demo.f_puntos(pmp),
        "detalle_cc_html": f"<div style='margin-top:10px;'><b>Imputación:</b>{filas_cc}</div>",
    }
    mail_ok = enviar_alerta_autorizacion(registro, usuario)
    resumen_cc = "; ".join(
        f"{c} {demo.f_decimal(l)} L (${demo.f_puntos(v)})" for c, l, v in lineas
    )
    return {
        "ok": True,
        "msg": (
            f"{codigo} autorizado e imputado: {demo.f_decimal(litros)} L → {resumen_cc}. "
            f"PMP ${demo.f_puntos(pmp)}/L. Ver Historial (arriba) y Costos."
        ),
        "mail_ok": mail_ok,
        "codigo": codigo,
    }


def rechazar_salida(codigo: str, usuario: str, motivo: str = "") -> dict[str, Any]:
    """Marca bitácora pendiente como rechazada; conserva el código correlativo."""
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    motivo = (motivo or "").strip()[:200]
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        # Columnas de rechazo (idempotente)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo_bitacora)").fetchall()}
        if "rechazado_por" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazado_por TEXT DEFAULT ''"
            )
        if "rechazado_en" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazado_en TEXT DEFAULT ''"
            )
        if "rechazo_motivo" not in cols:
            conn.execute(
                "ALTER TABLE petroleo_bitacora ADD COLUMN rechazo_motivo TEXT DEFAULT ''"
            )

        row = conn.execute(
            """SELECT COALESCE(estado, 'pendiente') FROM petroleo_bitacora WHERE codigo=?""",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        est = str(row[0] or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado; no se puede rechazar."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} ya está rechazado."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente (estado: {row[0]})."}

        fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE petroleo_bitacora
               SET estado='rechazado', rechazado_por=?, rechazado_en=?, rechazo_motivo=?
               WHERE codigo=?""",
            (usuario, fh, motivo, codigo),
        )
        det = f"{codigo} rechazado"
        if motivo:
            det += f" | {motivo}"
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (usuario, "PETROLEO RECHAZAR", det, fh),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "msg": f"{codigo} rechazado. El código se conserva en Salida Link (sin imputar al estanque).",
        "codigo": codigo,
    }


def _imputacion_por_codigo(conn, codigo: str) -> list[dict[str, Any]]:
    """Filas reales de petroleo generadas al autorizar (CC / litros / monto)."""
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    if not codigo:
        return []
    rows = conn.execute(
        """SELECT UPPER(TRIM(centro_costo)), litros, valor_imputado
           FROM petroleo
           WHERE bitacora_codigo = ? AND tipo = 'Salida'
           ORDER BY id""",
        (codigo,),
    ).fetchall()
    out = []
    for cc, litros_cc, valor in rows:
        out.append(
            {
                "cc": cc or "—",
                "litros": demo.f_decimal(litros_cc),
                "monto": demo.f_peso(valor or 0),
            }
        )
    return out


def listar_registros(conn, limite: int = 50) -> list[dict[str, Any]]:
    """Últimos registros de bitácora campo (ERP)."""
    demo = get_demo_module()
    migrar_tabla(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(petroleo_bitacora)").fetchall()}
    extra_sel = ""
    if "rechazado_por" in cols:
        extra_sel += ", COALESCE(rechazado_por, '')"
    else:
        extra_sel += ", ''"
    if "rechazado_en" in cols:
        extra_sel += ", COALESCE(rechazado_en, '')"
    else:
        extra_sel += ", ''"
    if "rechazo_motivo" in cols:
        extra_sel += ", COALESCE(rechazo_motivo, '')"
    else:
        extra_sel += ", ''"
    rows = conn.execute(
        f"""SELECT codigo, fecha_hora, litros, huerto, maquinaria, responsable,
                  COALESCE(estado, 'pendiente'), COALESCE(autorizado_por, ''),
                  COALESCE(autorizado_en, ''){extra_sel}
           FROM petroleo_bitacora
           ORDER BY id DESC
           LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for (
        codigo,
        fh,
        litros,
        huerto,
        maquinaria,
        responsable,
        estado,
        auth_por,
        auth_en,
        rej_por,
        rej_en,
        rej_mot,
    ) in rows:
        est = (estado or "pendiente").lower()
        imputaciones = [] if est != "autorizado" else _imputacion_por_codigo(conn, codigo or "")
        cc_imputados = ", ".join(
            f"{i['cc']} ({i['litros']} L · {i['monto']})" for i in imputaciones
        )
        out.append(
            {
                "codigo": codigo or "—",
                "fecha_hora": fh,
                "litros": demo.f_decimal(litros),
                "huerto": huerto or "—",
                "maquinaria": maquinaria,
                "responsable": responsable,
                "estado": est,
                "pendiente": est == "pendiente",
                "rechazado": est == "rechazado",
                "autorizado": est == "autorizado",
                "autorizado_por": auth_por,
                "autorizado_en": auth_en,
                "rechazado_por": rej_por,
                "rechazado_en": rej_en,
                "rechazo_motivo": rej_mot,
                "imputaciones": imputaciones,
                "cc_imputados": cc_imputados,
            }
        )
    return out


def contar_pendientes(conn) -> int:
    migrar_tabla(conn)
    row = conn.execute(
        """SELECT COUNT(*) FROM petroleo_bitacora
           WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'"""
    ).fetchone()
    return int(row[0] or 0) if row else 0


def aplicar_badge_menu_petroleo(opts, conn):
    from demo_web.services.sidebar_badges import aplicar_badges_labels_menu

    return aplicar_badges_labels_menu(opts, conn)


def datos_compartir() -> dict[str, str]:
    """URL pública genérica (legacy) + metadatos (requiere app context)."""
    migrar_tabla()
    tok = obtener_token()
    return {"url": url_publica(tok), "token": tok}


def links_personales_operadores() -> list[dict[str, str]]:
    """Un enlace fijo por responsable autorizado (para WhatsApp / favoritos)."""
    from urllib.parse import quote

    migrar_tabla()
    tok = obtener_token()
    out: list[dict[str, str]] = []
    for r in responsables_autorizados_para_formulario():
        op_id = str(r.get("id") or "").strip()
        nombre = str(r.get("nombre") or "").strip()
        if not op_id or not nombre:
            continue
        url = url_publica(tok, op=op_id)
        out.append(
            {
                "id": op_id,
                "nombre": nombre,
                "url": url,
                "wa_url": "https://wa.me/?text="
                + quote(f"Salida Link petróleo — {nombre}:\n{url}", safe=""),
            }
        )
    return out


def habilitado() -> bool:
    """Bitácora Salida Link + autorización: La Concepción y DEMO."""
    return get_erp_app() in ("concepcion", "demo")


def _nombre_erp() -> str:
    demo = get_demo_module()
    return str(getattr(demo, "NOMBRE_ERP", None) or "ERP Agrícola")
