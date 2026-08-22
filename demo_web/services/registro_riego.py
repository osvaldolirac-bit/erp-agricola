"""Registro de riego vía link personal + autorización admin (patrón Salida Link petróleo)."""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from flask import current_app, request

from demo_web.services.demo_loader import get_demo_module, get_erp_app

_CODIGO_RE = re.compile(r"^RIE-(\d+)$", re.I)


def _conn() -> sqlite3.Connection:
    demo = get_demo_module()
    return demo.conectar_db()


def formatear_codigo_rie(n: int) -> str:
    if n < 100:
        return f"RIE-{n:02d}"
    return f"RIE-{n}"


def _max_numero_codigo(conn: sqlite3.Connection, tabla: str) -> int:
    rows = conn.execute(
        f"SELECT codigo FROM {tabla} WHERE codigo IS NOT NULL AND codigo != ''"
    ).fetchall()
    max_n = 0
    for (cod,) in rows:
        m = _CODIGO_RE.match(str(cod).strip())
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _siguiente_codigo(conn: sqlite3.Connection, tabla: str = "riego_bitacora") -> str:
    n1 = _max_numero_codigo(conn, "riego_bitacora")
    n2 = _max_numero_codigo(conn, "riego")
    return formatear_codigo_rie(max(n1, n2) + 1)


def huertos_para_formulario() -> list[str]:
    demo = get_demo_module()
    raw = list(getattr(demo, "CENTROS_COSTO", []) or [])
    otros = [c for c in raw if str(c).strip().upper() == "OTROS"]
    resto = [c for c in raw if str(c).strip().upper() != "OTROS"]
    return resto + otros


def _ensure_mail_riego_usuarios(conn: sqlite3.Connection) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "mail_riego_bitacora" not in cols:
        conn.execute(
            "ALTER TABLE usuarios ADD COLUMN mail_riego_bitacora INTEGER DEFAULT 0"
        )


def _migrar_personal_regador(conn: sqlite3.Connection) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    if conn_en_solo_lectura(conn):
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(personal)").fetchall()}
    if "autorizado_registro_riego" not in cols:
        conn.execute(
            "ALTER TABLE personal ADD COLUMN autorizado_registro_riego INTEGER DEFAULT 0"
        )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autorizados_registro_riego_extra (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nombre TEXT NOT NULL UNIQUE,
               activo INTEGER DEFAULT 1,
               fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
           )"""
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
            """CREATE TABLE IF NOT EXISTS riego (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT UNIQUE,
                   fecha TEXT NOT NULL,
                   huerto TEXT NOT NULL,
                   horas REAL DEFAULT 0,
                   m3 REAL DEFAULT 0,
                   fert_dosis_ha REAL,
                   fert_total REAL,
                   regador TEXT DEFAULT '',
                   origen TEXT DEFAULT 'manual',
                   bitacora_codigo TEXT DEFAULT '',
                   creado_por TEXT DEFAULT '',
                   creado_en TEXT NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS riego_bitacora (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   codigo TEXT UNIQUE,
                   fecha TEXT NOT NULL,
                   huerto TEXT NOT NULL,
                   horas REAL DEFAULT 0,
                   m3 REAL DEFAULT 0,
                   fert_dosis_ha REAL,
                   fert_total REAL,
                   regador TEXT NOT NULL,
                   ip_origen TEXT,
                   creado_en TEXT NOT NULL,
                   estado TEXT DEFAULT 'pendiente',
                   autorizado_por TEXT DEFAULT '',
                   autorizado_en TEXT DEFAULT '',
                   rechazado_por TEXT DEFAULT '',
                   rechazado_en TEXT DEFAULT '',
                   rechazo_motivo TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
        )
        _migrar_personal_regador(conn)
        _ensure_mail_riego_usuarios(conn)
        row = conn.execute(
            "SELECT valor FROM schema_meta WHERE clave='registro_riego_token_v1'"
        ).fetchone()
        if not row:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT INTO schema_meta (clave, valor) VALUES ('registro_riego_token_v1', ?)",
                (token,),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def regadores_autorizados_para_formulario() -> list[dict[str, str]]:
    conn = _conn()
    try:
        migrar_tabla(conn)
        out: list[dict[str, str]] = []
        rows = conn.execute(
            """SELECT id, nombre FROM personal
               WHERE COALESCE(estado, 'Activo') = 'Activo'
                 AND COALESCE(autorizado_registro_riego, 0) = 1
               ORDER BY nombre"""
        ).fetchall()
        for rid, nombre in rows:
            out.append({"id": f"p-{rid}", "nombre": str(nombre)})
        extras = conn.execute(
            """SELECT id, nombre FROM autorizados_registro_riego_extra
               WHERE COALESCE(activo, 1) = 1 ORDER BY nombre"""
        ).fetchall()
        for eid, nombre in extras:
            out.append({"id": f"e-{eid}", "nombre": str(nombre)})
        out.sort(key=lambda x: x["nombre"].casefold())
        return out
    finally:
        conn.close()


_COOKIE_OP_MAX_AGE = 180 * 24 * 3600


def cookie_nombre_operador() -> str:
    app = get_erp_app() or "erp"
    return f"erp_sr_op_{app}"


def cookie_path_operador() -> str:
    return "/"


def resolver_regador_por_id(
    op_id: str | None,
    regadores: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    key = (op_id or "").strip()
    if not key:
        return None
    opts = regadores if regadores is not None else regadores_autorizados_para_formulario()
    for r in opts:
        if r.get("id") == key:
            return {"id": r["id"], "nombre": r["nombre"]}
    return None


def leer_operador_cookie(
    regadores: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    return resolver_regador_por_id(
        request.cookies.get(cookie_nombre_operador()),
        regadores,
    )


def aplicar_cookie_operador(response, op_id: str) -> None:
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


def _token_db(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave='registro_riego_token_v1'"
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
                "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES ('registro_riego_token_v1', ?)",
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
    from urllib.parse import quote

    tok = token or obtener_token()
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
    url = f"{base}{prefix}/registro-riego?t={tok}"
    op_id = (op or "").strip()
    if op_id:
        url += f"&op={quote(op_id, safe='')}"
    return url


def _destinatario_alerta() -> list[str]:
    demo = get_demo_module()
    if hasattr(demo, "obtener_destinatarios_riego_bitacora"):
        conn = demo.conectar_db()
        try:
            dest = list(demo.obtener_destinatarios_riego_bitacora(conn))
            if dest:
                return dest
        finally:
            conn.close()
    conn = _conn()
    try:
        migrar_tabla(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "mail_riego_bitacora" in cols:
            rows = conn.execute(
                "SELECT email FROM usuarios WHERE COALESCE(mail_riego_bitacora, 0) = 1"
            ).fetchall()
            dest = [str(r[0]).strip() for r in rows if r and r[0]]
            if dest:
                return dest
    finally:
        conn.close()
    conf = demo._conf_smtp_prod() if hasattr(demo, "_conf_smtp_prod") else None
    if conf and conf.get("receptor_admin"):
        return [str(conf["receptor_admin"]).strip()]
    return []


def _nombre_erp() -> str:
    demo = get_demo_module()
    return str(getattr(demo, "NOMBRE_ERP", None) or "ERP Agrícola")


def _fmt_fert(dosis, total, demo) -> str:
    parts = []
    if dosis is not None and float(dosis or 0) > 0:
        parts.append(f"dosis {demo.f_decimal(dosis)} x ha")
    if total is not None and float(total or 0) > 0:
        parts.append(f"total {demo.f_decimal(total)}")
    return " · ".join(parts) if parts else "—"


def enviar_alerta(registro: dict[str, Any]) -> bool:
    demo = get_demo_module()
    if not hasattr(demo, "_enviar_correo_html"):
        return False
    from erp_correo_html import html_esc, plantilla_correo_html

    dest = _destinatario_alerta()
    if not dest:
        return False
    codigo = registro.get("codigo", "")
    fert = registro.get("fert_txt", "—")
    interior = f"""
        <p style="color:#1F2933;line-height:1.55;margin:0 0 12px;">
          Se registró un riego desde <b>Registro Link</b>. Un administrador debe
          <b>autorizarlo</b> en Riego → Ingreso para imputarlo al centro de costo.
        </p>
        <div style="background:#E3F2FD;border:1px solid #90CAF9;border-radius:10px;padding:16px 18px;">
          <p style="margin:6px 0;"><b>Código:</b> {html_esc(codigo)}</p>
          <p style="margin:6px 0;"><b>Fecha:</b> {html_esc(registro.get('fecha', ''))}</p>
          <p style="margin:6px 0;"><b>Huerto:</b> {html_esc(registro.get('huerto', ''))}</p>
          <p style="margin:6px 0;"><b>Horas:</b> {html_esc(registro.get('horas_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>m³:</b> {html_esc(registro.get('m3_fmt', ''))}</p>
          <p style="margin:6px 0;"><b>Fertilización:</b> {html_esc(fert)}</p>
          <p style="margin:6px 0;"><b>Regador:</b> {html_esc(registro.get('regador', ''))}</p>
        </div>
    """
    cuerpo = plantilla_correo_html(
        "vencimiento",
        f"💧 {codigo} — Registro Link riego",
        interior,
        nombre_erp=_nombre_erp(),
        pie="Registro informativo vía link personal. Pendiente de autorización.",
    )
    asunto = f"💧 {codigo} | {registro.get('huerto', '')[:20]} | {registro.get('regador', '')[:20]}"
    return bool(demo._enviar_correo_html(asunto, cuerpo, dest))


def registrar_link(
    fecha: str,
    huerto: str,
    horas: float,
    m3: float,
    regador: str,
    *,
    fert_dosis_ha: float | None = None,
    fert_total: float | None = None,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto = (huerto or "").strip().upper()
    regador = (regador or "").strip()
    fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()

    conn = _conn()
    try:
        migrar_tabla(conn)
        conn.execute("BEGIN IMMEDIATE")
        codigo = _siguiente_codigo(conn)
        conn.execute(
            """INSERT INTO riego_bitacora
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, ip_origen, creado_en, estado)
               VALUES (?,?,?,?,?,?,?,?,?,?,'pendiente')""",
            (
                codigo,
                fecha,
                huerto,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                regador,
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
        "fecha": fecha,
        "huerto": huerto,
        "horas_fmt": demo.f_decimal(horas),
        "m3_fmt": demo.f_decimal(m3),
        "fert_txt": _fmt_fert(fert_dosis_ha, fert_total, demo),
        "regador": regador,
    }
    mail_ok = enviar_alerta(registro)
    try:
        conn = _conn()
        det = (
            f"Link | {codigo} | {huerto} | {registro['horas_fmt']} h | "
            f"{registro['m3_fmt']} m3 | {regador[:40]}"
            + (" | mail OK" if mail_ok else " | mail falló")
        )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            ("BITACORA-RIEGO", "RIEGO LINK", det, fh),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"ok": True, "mail_ok": mail_ok, **registro}


def autorizar_registro(codigo: str, usuario: str) -> dict[str, Any]:
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        row = conn.execute(
            """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                      regador, COALESCE(estado, 'pendiente')
               FROM riego_bitacora WHERE codigo=?""",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            fert_dosis_ha,
            fert_total,
            regador,
            estado,
        ) = row
        est = str(estado or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} está rechazado."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente."}

        huerto_cc = str(huerto or "").strip().upper()
        if not huerto_cc:
            return {"ok": False, "msg": "Huerto inválido."}

        fh_auth = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, origen, bitacora_codigo, creado_por, creado_en)
               VALUES (?,?,?,?,?,?,?,?, 'link', ?, ?, ?)""",
            (
                codigo,
                str(fecha)[:10],
                huerto_cc,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                regador,
                codigo,
                usuario,
                fh_auth,
            ),
        )
        conn.execute(
            """UPDATE riego_bitacora
               SET estado='autorizado', autorizado_por=?, autorizado_en=?
               WHERE codigo=?""",
            (usuario, fh_auth, codigo),
        )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                usuario,
                "RIEGO AUTORIZAR",
                f"{codigo} | {huerto_cc} | {demo.f_decimal(horas)} h | {demo.f_decimal(m3)} m3",
                fh_auth,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "msg": (
            f"{codigo} autorizado e imputado al CC {huerto_cc}. "
            f"{demo.f_decimal(horas)} h · {demo.f_decimal(m3)} m³."
        ),
        "codigo": codigo,
    }


def rechazar_registro(codigo: str, usuario: str, motivo: str = "") -> dict[str, Any]:
    demo = get_demo_module()
    codigo = (codigo or "").strip()
    usuario = (usuario or "").strip() or "admin"
    motivo = (motivo or "").strip()[:200]
    if not codigo:
        return {"ok": False, "msg": "Código inválido."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        row = conn.execute(
            "SELECT COALESCE(estado, 'pendiente') FROM riego_bitacora WHERE codigo=?",
            (codigo,),
        ).fetchone()
        if not row:
            return {"ok": False, "msg": f"No se encontró {codigo}."}
        est = str(row[0] or "pendiente").lower()
        if est == "autorizado":
            return {"ok": False, "msg": f"{codigo} ya está autorizado."}
        if est == "rechazado":
            return {"ok": False, "msg": f"{codigo} ya está rechazado."}
        if est != "pendiente":
            return {"ok": False, "msg": f"{codigo} no está pendiente."}

        fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE riego_bitacora
               SET estado='rechazado', rechazado_por=?, rechazado_en=?, rechazo_motivo=?
               WHERE codigo=?""",
            (usuario, fh, motivo, codigo),
        )
        det = f"{codigo} rechazado"
        if motivo:
            det += f" | {motivo}"
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (usuario, "RIEGO RECHAZAR", det, fh),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "msg": f"{codigo} rechazado (sin imputar al CC).",
        "codigo": codigo,
    }


def registrar_manual(
    fecha: str,
    huerto: str,
    horas: float,
    m3: float,
    regador: str,
    usuario: str,
    *,
    fert_dosis_ha: float | None = None,
    fert_total: float | None = None,
) -> dict[str, Any]:
    demo = get_demo_module()
    huerto_cc = (huerto or "").strip().upper()
    if not huerto_cc:
        return {"ok": False, "msg": "Seleccione huerto."}

    conn = _conn()
    try:
        migrar_tabla(conn)
        conn.execute("BEGIN IMMEDIATE")
        codigo = _siguiente_codigo(conn)
        fh = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                regador, origen, creado_por, creado_en)
               VALUES (?,?,?,?,?,?,?,?, 'manual', ?, ?)""",
            (
                codigo,
                str(fecha)[:10],
                huerto_cc,
                float(horas or 0),
                float(m3 or 0),
                fert_dosis_ha,
                fert_total,
                (regador or usuario or "").strip(),
                usuario,
                fh,
            ),
        )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                usuario,
                "RIEGO MANUAL",
                f"{codigo} | {huerto_cc} | {demo.f_decimal(horas)} h | {demo.f_decimal(m3)} m3",
                fh,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "msg": f"{codigo} registrado en {huerto_cc}.", "codigo": codigo}


def listar_bitacora(conn, limite: int = 50) -> list[dict[str, Any]]:
    demo = get_demo_module()
    migrar_tabla(conn)
    rows = conn.execute(
        """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total, regador,
                  COALESCE(estado, 'pendiente'), COALESCE(autorizado_por, ''),
                  COALESCE(autorizado_en, ''), COALESCE(rechazado_por, ''),
                  COALESCE(rechazado_en, ''), COALESCE(rechazo_motivo, ''), creado_en
           FROM riego_bitacora ORDER BY id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for row in rows:
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            dosis,
            total,
            regador,
            estado,
            auth_por,
            auth_en,
            rej_por,
            rej_en,
            rej_mot,
            creado,
        ) = row
        est = (estado or "pendiente").lower()
        out.append(
            {
                "codigo": codigo or "—",
                "fecha": str(fecha or "")[:10],
                "huerto": huerto or "—",
                "horas": demo.f_decimal(horas),
                "m3": demo.f_decimal(m3),
                "fert_txt": _fmt_fert(dosis, total, demo),
                "regador": regador,
                "estado": est,
                "pendiente": est == "pendiente",
                "rechazado": est == "rechazado",
                "autorizado": est == "autorizado",
                "autorizado_por": auth_por,
                "autorizado_en": auth_en,
                "rechazado_por": rej_por,
                "rechazado_en": rej_en,
                "rechazo_motivo": rej_mot,
                "creado_en": creado,
            }
        )
    return out


def listar_historial(conn, limite: int = 100) -> list[dict[str, Any]]:
    demo = get_demo_module()
    migrar_tabla(conn)
    rows = conn.execute(
        """SELECT codigo, fecha, huerto, horas, m3, fert_dosis_ha, fert_total,
                  regador, origen, bitacora_codigo, creado_por, creado_en
           FROM riego ORDER BY fecha DESC, id DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    out = []
    for i, row in enumerate(rows, start=1):
        (
            codigo,
            fecha,
            huerto,
            horas,
            m3,
            dosis,
            total,
            regador,
            origen,
            bit_cod,
            creado_por,
            creado_en,
        ) = row
        out.append(
            {
                "num": i,
                "codigo": codigo or "—",
                "fecha": str(fecha or "")[:10],
                "huerto": huerto or "—",
                "horas": demo.f_decimal(horas),
                "m3": demo.f_decimal(m3),
                "fert_txt": _fmt_fert(dosis, total, demo),
                "regador": regador or "—",
                "origen": origen or "manual",
                "bitacora_codigo": bit_cod or "",
                "creado_por": creado_por or "",
                "creado_en": creado_en or "",
            }
        )
    return out


def contar_pendientes(conn) -> int:
    migrar_tabla(conn)
    row = conn.execute(
        """SELECT COUNT(*) FROM riego_bitacora
           WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'"""
    ).fetchone()
    return int(row[0] or 0) if row else 0


def links_personales_regadores() -> list[dict[str, str]]:
    from urllib.parse import quote

    migrar_tabla()
    tok = obtener_token()
    out: list[dict[str, str]] = []
    for r in regadores_autorizados_para_formulario():
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
                + quote(f"Registro Link riego — {nombre}:\n{url}", safe=""),
            }
        )
    return out


def habilitado() -> bool:
    return get_erp_app() in ("concepcion", "demo")
