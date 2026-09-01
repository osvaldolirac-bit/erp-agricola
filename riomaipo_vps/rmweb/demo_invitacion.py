"""Invitaciones y vigencia DEMO Comercial (paridad con DEMO Agrícola)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from rmweb.mail_alertas import html_mail_sender, receptor_admin

DEMO_DIAS_PRUEBA = 30
DEMO_URL = os.environ.get(
    "COMERCIAL_DEMO_URL",
    "https://erpmaster.cl/comercial/login?tenant=comercial-demo",
)
NOMBRE_ERP = "DEMO Comercial"


def login_url_invitado(email: str, tenant_slug: str = "comercial-demo") -> str:
    """Login DEMO con correo del invitado precargado y tenant destino."""
    from urllib.parse import quote

    e = (email or "").strip().lower()
    slug = (tenant_slug or "comercial-demo").strip().lower()
    if slug == "taller-demo":
        base = os.environ.get(
            "TALLER_DEMO_URL",
            "https://erpmaster.cl/comercial/login?tenant=taller-demo",
        )
    else:
        base = DEMO_URL
    if "acceso=" in base:
        return base
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}acceso={quote(e)}"
    if slug and "tenant=" not in base:
        url += f"&tenant={quote(slug)}"
    return url

# Cuentas permanentes (sin vencimiento) en DEMO Comercial
USUARIOS_PERMANENTES = {
    "osvaldolira@constructorariomaipo.cl",
    "osvaldolirac@gmail.com",
    "osvaldolira@laconcepcion.cl",
}


def _hora_chile() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=4)


def hoy_chile() -> date:
    return _hora_chile().date()


def parse_fecha(fecha_expira: str | None) -> date | None:
    raw = str(fecha_expira or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def dias_restantes_prueba(fecha_expira: str | None, ref: date | None = None) -> int | None:
    fexp = parse_fecha(fecha_expira)
    if not fexp:
        return None
    return (fexp - (ref or hoy_chile())).days


def usuario_prueba_vigente(fecha_expira: str | None) -> bool:
    fexp = parse_fecha(fecha_expira)
    if not fexp:
        return True
    return fexp >= hoy_chile()


def fecha_fin_prueba(dias: int = DEMO_DIAS_PRUEBA, desde: date | None = None) -> str:
    d = max(1, int(dias or DEMO_DIAS_PRUEBA))
    return ((desde or hoy_chile()) + timedelta(days=d)).isoformat()


def es_permanente(email: str) -> bool:
    return str(email or "").strip().lower() in USUARIOS_PERMANENTES


def acceso_permitido_en_tenant(slug: str | None, user: dict[str, Any] | None) -> bool:
    """Invitados de prueba solo en su tenant_slug; internos en todos."""
    u = user or {}
    if es_permanente(u.get("usuario") or ""):
        return True
    home = str(u.get("tenant_slug") or "").strip().lower()
    if home:
        return (slug or "").strip().lower() == home
    invitado = str(u.get("invitado_por") or "").strip()
    expira = str(u.get("fecha_expira") or "").strip()
    if invitado or expira:
        return (slug or "").strip().lower() == (home or "comercial-demo")
    return True


def tenant_slug_usuario(user: dict[str, Any] | None) -> str:
    u = user or {}
    home = str(u.get("tenant_slug") or "").strip().lower()
    if home:
        return home
    if es_permanente(u.get("usuario") or ""):
        return ""
    if str(u.get("invitado_por") or "").strip() or str(u.get("fecha_expira") or "").strip():
        return "comercial-demo"
    return ""


def enviar_correo_invitacion_demo(
    *,
    secrets_path: str,
    email: str,
    password_plain: str,
    rol: str,
    admin_email: str,
    fecha_expira: str,
    dias: int = DEMO_DIAS_PRUEBA,
) -> tuple[bool, str]:
    from erp_correo_html import html_esc, plantilla_correo_html

    send = html_mail_sender(secrets_path)
    if not send:
        return False, "No se pudo enviar la invitación (revise SMTP)."

    f_h = _hora_chile().strftime("%d-%m-%Y %H:%M")
    f_exp = parse_fecha(fecha_expira)
    f_exp_txt = f_exp.strftime("%d-%m-%Y") if f_exp else str(fecha_expira or "")[:10]
    email_n = (email or "").strip()
    admin = (admin_email or receptor_admin(secrets_path) or "").strip()
    n_dias = max(1, int(dias or DEMO_DIAS_PRUEBA))
    link_acceso = login_url_invitado(email_n)

    interior = f"""
            <p style="color:#1F2933;line-height:1.55;">
                Has sido invitado a probar el <b>ERP Master Comercial</b> en entorno de demostración.
                Este acceso es temporal y sirve para conocer el sistema sin afectar datos de producción.
            </p>
            <div style="background:#E0F7FA;border:1px solid #80DEEA;border-radius:10px;padding:14px 18px;margin:18px 0;">
                <p style="margin:0;color:#0F4C5C;font-weight:700;">⏳ Periodo de prueba: {n_dias} días</p>
                <p style="margin:8px 0 0;color:#0F4C5C;">
                  Su acceso estará vigente hasta el <b>{html_esc(f_exp_txt)}</b> (inclusive).
                  Recibirá avisos automáticos por correo <b>24 horas antes</b> y <b>al vencer el plazo</b>.
                </p>
            </div>
            <div style="background:#E0F2F1;border:1px solid #80CBC4;border-radius:10px;padding:18px 20px;margin:18px 0;">
                <p style="margin:0 0 10px;font-weight:800;color:#00695C;">📋 Datos de acceso</p>
                <p style="margin:6px 0;"><b>Usuario:</b> <span style="color:#00695C;font-weight:bold;">{html_esc(email_n)}</span></p>
                <p style="margin:6px 0;"><b>Contraseña:</b> <span style="color:#00695C;font-weight:bold;">{html_esc(password_plain)}</span></p>
                <p style="margin:6px 0;"><b>Perfil:</b> {html_esc(rol or "Operador")}</p>
                <p style="margin:6px 0;"><b>Enlace:</b> <a href="{link_acceso}" style="color:#00695C;font-weight:bold;">{link_acceso}</a></p>
            </div>
            <p style="text-align:center;margin:24px 0;">
                <a href="{link_acceso}" style="display:inline-block;background:linear-gradient(135deg,#0F8FA8,#00695C);color:white;text-decoration:none;padding:12px 28px;border-radius:10px;font-weight:800;">
                  ACCEDER AL ERP DEMO COMERCIAL
                </a>
            </p>
            <p style="font-size:13px;color:#5F6B7A;margin:6px 0;"><b>Fecha:</b> {html_esc(f_h)} (Chile)</p>
    """
    cuerpo = plantilla_correo_html(
        "invitacion",
        "Bienvenido al ERP Master Comercial — Ambiente Demo",
        interior,
        nombre_erp=NOMBRE_ERP,
        pie="Si no esperaba esta invitación, ignore el correo.",
    )
    ok = bool(
        send(
            f"Invitación — ERP Comercial Demo (acceso de prueba {n_dias} días)",
            cuerpo,
            [email_n],
        )
    )
    # Copia al admin (si es distinto)
    if admin and admin.lower() != email_n.lower():
        try:
            send(
                f"Copia — Invitación Comercial Demo enviada a {email_n}",
                cuerpo,
                [admin],
            )
        except Exception:
            pass
    if ok:
        return True, f"Correo de invitación enviado a {email_n}."
    return False, "No se pudo enviar el correo de invitación (revise SMTP)."


def _enviar_alerta_vencimiento(
    *,
    secrets_path: str,
    email_usuario: str,
    fecha_expira: str,
    modo: str,  # "24h" | "vencido"
) -> bool:
    from erp_correo_html import html_esc, plantilla_correo_html

    send = html_mail_sender(secrets_path)
    if not send:
        return False
    f_exp = parse_fecha(fecha_expira)
    f_exp_txt = f_exp.strftime("%d-%m-%Y") if f_exp else str(fecha_expira or "")[:10]
    f_h = _hora_chile().strftime("%d-%m-%Y %H:%M")
    admin = receptor_admin(secrets_path)
    email_u = (email_usuario or "").strip()

    if modo == "24h":
        titulo_u = "Su periodo de prueba termina pronto"
        cuerpo_u = f"""
            <p>Su acceso al <b>ERP Master Comercial Demo</b> finalizará el <b>{html_esc(f_exp_txt)}</b>.</p>
            <p>Le queda aproximadamente <b>1 día</b> para utilizar el entorno de demostración.</p>
            <p><b>Enlace:</b> <a href="{DEMO_URL}">{DEMO_URL}</a></p>
            <p>Si necesita extender el periodo, contacte al administrador que lo invitó.</p>
            <p style="font-size:13px;color:#5F6B7A;"><b>Fecha aviso:</b> {html_esc(f_h)}</p>
        """
        asunto_u = f"Aviso: su prueba Comercial Demo termina el {f_exp_txt}"
        titulo_a = "Usuario Comercial Demo por vencer (24 h)"
        cuerpo_a = f"""
            <p>El siguiente usuario de prueba del <b>DEMO Comercial</b> termina su vigencia en ~24 horas:</p>
            <p><b>Usuario:</b> {html_esc(email_u)}</p>
            <p><b>Fecha término:</b> {html_esc(f_exp_txt)}</p>
            <p>Puede extender el acceso desde Super Consola → Usuarios.</p>
        """
        asunto_a = f"Aviso admin: prueba Comercial Demo de {email_u} termina el {f_exp_txt}"
    else:
        titulo_u = "Su periodo de prueba ha finalizado"
        cuerpo_u = f"""
            <p>Su periodo de prueba del <b>ERP Master Comercial Demo</b> <b>venció</b> el {html_esc(f_exp_txt)}.</p>
            <p>Ya no puede ingresar con este usuario. Si necesita más tiempo, contacte al administrador que lo invitó.</p>
            <p style="font-size:13px;color:#5F6B7A;"><b>Fecha aviso:</b> {html_esc(f_h)}</p>
        """
        asunto_u = f"Su acceso Comercial Demo venció el {f_exp_txt}"
        titulo_a = "Usuario Comercial Demo — plazo vencido"
        cuerpo_a = f"""
            <p>El periodo de prueba del usuario <b>{html_esc(email_u)}</b> en DEMO Comercial <b>venció</b> el {html_esc(f_exp_txt)}.</p>
            <p>Puede extender el acceso o eliminar el usuario desde Super Consola → Usuarios.</p>
        """
        asunto_a = f"Venció prueba Comercial Demo de {email_u} ({f_exp_txt})"

    html_u = plantilla_correo_html("vencimiento", titulo_u, cuerpo_u, nombre_erp=NOMBRE_ERP)
    ok_u = bool(send(asunto_u, html_u, [email_u]))
    ok_a = True
    if admin and admin.lower() != email_u.lower():
        html_a = plantilla_correo_html("vencimiento", titulo_a, cuerpo_a, nombre_erp=NOMBRE_ERP)
        ok_a = bool(send(asunto_a, html_a, [admin]))
    return ok_u and ok_a


def procesar_alertas_vencimiento_comercial_demo(
    db_path: str,
    secrets_path: str,
) -> dict[str, Any]:
    """Cron diario: aviso 24h y aviso vencido (paridad agrícola)."""
    import sqlite3

    if not db_path or not os.path.isfile(db_path):
        return {"ok": False, "error": "sin_db", "enviados_24h": 0, "enviados_vencido": 0}
    if not html_mail_sender(secrets_path):
        return {"ok": False, "error": "sin_smtp", "enviados_24h": 0, "enviados_vencido": 0}

    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
    for col, decl in (
        ("fecha_expira", "TEXT"),
        ("invitado_por", "TEXT"),
        ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
        ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {decl}")
    conn.commit()

    ref = hoy_chile()
    n24 = nv = 0
    rows = conn.execute(
        """
        SELECT usuario, fecha_expira,
               COALESCE(alerta_24h_enviada, 0), COALESCE(alerta_vencido_enviada, 0)
        FROM usuarios
        WHERE fecha_expira IS NOT NULL AND TRIM(fecha_expira) != ''
        """
    ).fetchall()
    for usuario, fecha_exp, flg_24h, flg_v in rows:
        if es_permanente(usuario):
            continue
        dias = dias_restantes_prueba(fecha_exp, ref)
        if dias is None:
            continue
        if dias == 1 and not int(flg_24h or 0):
            if _enviar_alerta_vencimiento(
                secrets_path=secrets_path,
                email_usuario=usuario,
                fecha_expira=fecha_exp,
                modo="24h",
            ):
                conn.execute(
                    "UPDATE usuarios SET alerta_24h_enviada=1 WHERE lower(usuario)=lower(?)",
                    (usuario,),
                )
                conn.commit()
                n24 += 1
        elif dias < 0 and not int(flg_v or 0):
            if _enviar_alerta_vencimiento(
                secrets_path=secrets_path,
                email_usuario=usuario,
                fecha_expira=fecha_exp,
                modo="vencido",
            ):
                conn.execute(
                    "UPDATE usuarios SET alerta_vencido_enviada=1 WHERE lower(usuario)=lower(?)",
                    (usuario,),
                )
                conn.commit()
                nv += 1
    conn.close()
    return {"ok": True, "enviados_24h": n24, "enviados_vencido": nv}


# ── Verificación OTP para /probar (DEMO Comercial) ────────────────────────
OTP_TTL_SEC = 15 * 60
OTP_RESEND_COOLDOWN_SEC = 60
OTP_MAX_ATTEMPTS = 3
OTP_STORE_NAME = "probar_otp_comercial.json"


def _otp_store_path() -> str:
    import os

    status_dir = (os.environ.get("ERP_STATUS_DIR") or "/root/erp_status").strip() or "/root/erp_status"
    try:
        os.makedirs(status_dir, exist_ok=True)
    except Exception:
        status_dir = "/tmp"
    return os.path.join(status_dir, OTP_STORE_NAME)


def _otp_load() -> dict:
    import json
    import os

    path = _otp_store_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _otp_save(data: dict) -> None:
    import json
    import os
    import tempfile

    path = _otp_store_path()
    fd, tmp = tempfile.mkstemp(prefix="otp_", suffix=".json", dir=os.path.dirname(path) or "/tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _otp_purge_expired(data: dict) -> dict:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).timestamp()
    out = {}
    for k, v in (data or {}).items():
        try:
            if float(v.get("expires_at") or 0) > now:
                out[k] = v
        except Exception:
            continue
    return out


def _otp_hash(code: str, salt: str) -> str:
    import hashlib

    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def crear_y_enviar_codigo_probar(
    *,
    secrets_path: str,
    email: str,
    nombre: str,
    telefono: str,
    force_resend: bool = False,
) -> tuple[bool, str, dict | None]:
    """Genera OTP, lo guarda y envía el mail con el código. No crea usuario."""
    import secrets
    from datetime import datetime, timezone

    from erp_correo_html import html_esc, plantilla_correo_html
    from rmweb.mail_alertas import html_mail_sender

    email_n = (email or "").strip().lower()
    if not email_n or "@" not in email_n:
        return False, "Correo inválido.", None

    send = html_mail_sender(secrets_path)
    if not send:
        return False, "No se pudo enviar el código (revise SMTP).", None

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    data = _otp_purge_expired(_otp_load())
    prev = data.get(email_n) or {}
    if prev and not force_resend:
        # Si aún no vence y no piden reenvío explícito, reutiliza pantalla.
        try:
            if float(prev.get("expires_at") or 0) > now_ts and int(prev.get("attempts") or 0) < OTP_MAX_ATTEMPTS:
                sent_at = float(prev.get("sent_at") or 0)
                wait = int(OTP_RESEND_COOLDOWN_SEC - (now_ts - sent_at))
                meta = {
                    "email": email_n,
                    "nombre": prev.get("nombre") or nombre,
                    "telefono": prev.get("telefono") or telefono,
                    "resend_wait": max(0, wait),
                }
                return True, "Ya enviamos un código a tu correo. Revísalo o reenvía si no llegó.", meta
        except Exception:
            pass
    if force_resend and prev:
        sent_at = float(prev.get("sent_at") or 0)
        wait = int(OTP_RESEND_COOLDOWN_SEC - (now_ts - sent_at))
        if wait > 0:
            meta = {
                "email": email_n,
                "nombre": prev.get("nombre") or nombre,
                "telefono": prev.get("telefono") or telefono,
                "resend_wait": wait,
            }
            return False, f"Espera {wait}s para reenviar el código.", meta

    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(8)
    entry = {
        "nombre": (nombre or "").strip()[:120],
        "telefono": (telefono or "").strip()[:40],
        "salt": salt,
        "code_hash": _otp_hash(code, salt),
        "expires_at": now_ts + OTP_TTL_SEC,
        "sent_at": now_ts,
        "attempts": 0,
        "created_at": now.isoformat(),
    }
    data[email_n] = entry
    _otp_save(data)

    interior = f"""
            <p style="color:#1F2933;line-height:1.55;">
                Hola{(' ' + html_esc(entry['nombre'])) if entry['nombre'] else ''},
                para activar tu prueba del <b>ERP Master Comercial</b> ingresa este código:
            </p>
            <div style="background:#E0F2F1;border:1px solid #80CBC4;border-radius:12px;padding:18px 20px;margin:22px 0;text-align:center;">
                <p style="margin:0 0 8px;font-size:13px;color:#00695C;font-weight:700;letter-spacing:.08em;">CÓDIGO DE VERIFICACIÓN</p>
                <p style="margin:0;font-size:32px;letter-spacing:.35em;font-weight:800;color:#004D40;">{html_esc(code)}</p>
            </div>
            <p style="color:#5F6B7A;font-size:14px;">Válido por <b>15 minutos</b>. Si no solicitaste este acceso, ignora el correo.</p>
    """
    cuerpo = plantilla_correo_html(
        "invitacion",
        "Tu código para probar ERP Comercial",
        interior,
        nombre_erp=NOMBRE_ERP,
        pie="No compartas este código. ERP Master.",
    )
    ok = bool(send(f"Código de verificación — ERP Comercial Demo", cuerpo, [email_n]))
    meta = {
        "email": email_n,
        "nombre": entry["nombre"],
        "telefono": entry["telefono"],
        "resend_wait": OTP_RESEND_COOLDOWN_SEC,
    }
    if ok:
        return True, f"Enviamos un código a {email_n}.", meta
    # Si falló el mail, borra el pending
    data.pop(email_n, None)
    _otp_save(data)
    return False, "No se pudo enviar el correo con el código. Revisa el mail o intenta más tarde.", None


def validar_codigo_probar(email: str, codigo: str) -> tuple[bool, str, dict | None]:
    """Valida OTP. Máx. 3 intentos; luego hay que pedir otro código."""
    from datetime import datetime, timezone

    email_n = (email or "").strip().lower()
    code = "".join(ch for ch in (codigo or "").strip() if ch.isdigit())
    data = _otp_purge_expired(_otp_load())
    entry = data.get(email_n)
    if not entry:
        return False, "No hay un código vigente. Solicita uno nuevo.", None
    now_ts = datetime.now(timezone.utc).timestamp()
    if float(entry.get("expires_at") or 0) <= now_ts:
        data.pop(email_n, None)
        _otp_save(data)
        return False, "El código expiró. Solicita uno nuevo.", None
    attempts = int(entry.get("attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        data.pop(email_n, None)
        _otp_save(data)
        return False, "Se agotaron los 3 intentos. Solicita un código nuevo.", None
    if len(code) != 6 or _otp_hash(code, entry.get("salt") or "") != entry.get("code_hash"):
        entry["attempts"] = attempts + 1
        left = OTP_MAX_ATTEMPTS - entry["attempts"]
        if left <= 0:
            data.pop(email_n, None)
            _otp_save(data)
            return False, "Código incorrecto. Se agotaron los 3 intentos; solicita uno nuevo.", None
        data[email_n] = entry
        _otp_save(data)
        return False, f"Código incorrecto. Te quedan {left} intento(s).", {
            "email": email_n,
            "nombre": entry.get("nombre") or "",
            "telefono": entry.get("telefono") or "",
            "resend_wait": 0,
        }
    # OK — entregar datos y borrar pending
    payload = {
        "email": email_n,
        "nombre": entry.get("nombre") or "",
        "telefono": entry.get("telefono") or "",
    }
    data.pop(email_n, None)
    _otp_save(data)
    return True, "Correo verificado.", payload


