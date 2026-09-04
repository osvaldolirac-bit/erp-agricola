"""Formulario público /probar DEMO Agrícola (paridad Comercial / IG)."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import smtplib
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

DEMO_DIAS_PRUEBA = 30
CLAVE_DEMO = "1234"
ROL_DEMO = "admin_cliente"
OTP_TTL_SEC = 15 * 60
OTP_RESEND_COOLDOWN_SEC = 60
OTP_MAX_ATTEMPTS = 3
OTP_STORE_NAME = "probar_otp_agricola.json"
LEADS_NAME = "leads_demo_agricola.jsonl"

USUARIOS_PERMANENTES = {
    "osvaldolira@laconcepcion.cl",
    "demo@erpmaster.cl",
    "certificacion@erpmaster.cl",
    "osvaldolirac@gmail.com",
}


def _hora_chile() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=4)


def hoy_chile() -> date:
    return _hora_chile().date()


def fecha_fin_prueba(dias: int = DEMO_DIAS_PRUEBA) -> str:
    return (hoy_chile() + timedelta(days=max(1, int(dias)))).isoformat()


def es_permanente(email: str) -> bool:
    return (email or "").strip().lower() in USUARIOS_PERMANENTES


def hash_password(password: str) -> str:
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def usuario_prueba_vigente(fecha_expira: str | None) -> bool:
    raw = str(fecha_expira or "").strip()
    if not raw:
        return True
    try:
        fexp = date.fromisoformat(raw[:10])
    except ValueError:
        return True
    return fexp >= hoy_chile()


def _status_dir() -> str:
    status_dir = (os.environ.get("ERP_STATUS_DIR") or "/root/erp_status").strip() or "/root/erp_status"
    try:
        os.makedirs(status_dir, exist_ok=True)
    except Exception:
        status_dir = "/tmp"
    return status_dir


def _otp_store_path() -> str:
    return os.path.join(_status_dir(), OTP_STORE_NAME)


def _otp_load() -> dict:
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
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _smtp_send(secrets_path: str, *, to: str, subject: str, html: str) -> bool:
    import sys

    sys.path.insert(0, "/root/demo-web")
    from erp_respaldo import cargar_smtp

    smtp = cargar_smtp(secrets_path or "")
    if not smtp:
        return False
    emisor = smtp["emisor"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp.get("from_header") or emisor
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(emisor, smtp["clave"])
        server.sendmail(emisor, [to], msg.as_string())
        server.quit()
        return True
    except Exception:
        return False


def crear_y_enviar_codigo_probar(
    *,
    secrets_path: str,
    email: str,
    nombre: str,
    telefono: str,
    force_resend: bool = False,
) -> tuple[bool, str, dict | None]:
    from erp_correo_html import html_esc, plantilla_correo_html

    email_n = (email or "").strip().lower()
    if not email_n or "@" not in email_n:
        return False, "Correo inválido.", None

    now_ts = datetime.now(timezone.utc).timestamp()
    data = _otp_purge_expired(_otp_load())
    prev = data.get(email_n) or {}
    sent_at = float(prev.get("sent_at") or 0)
    if prev and not force_resend:
        if float(prev.get("expires_at") or 0) > now_ts and int(prev.get("attempts") or 0) < OTP_MAX_ATTEMPTS:
            wait = int(OTP_RESEND_COOLDOWN_SEC - (now_ts - sent_at))
            if wait > 0:
                return (
                    False,
                    f"Ya enviamos un código. Espera {wait}s para reenviar.",
                    {
                        "email": email_n,
                        "nombre": prev.get("nombre") or nombre,
                        "telefono": prev.get("telefono") or telefono,
                        "resend_wait": wait,
                    },
                )
    if force_resend and sent_at:
        wait = int(OTP_RESEND_COOLDOWN_SEC - (now_ts - sent_at))
        if wait > 0:
            return (
                False,
                f"Espera {wait}s para reenviar el código.",
                {
                    "email": email_n,
                    "nombre": prev.get("nombre") or nombre,
                    "telefono": prev.get("telefono") or telefono,
                    "resend_wait": wait,
                },
            )

    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(8)
    data[email_n] = {
        "hash": _otp_hash(code, salt),
        "salt": salt,
        "nombre": (nombre or "").strip()[:120],
        "telefono": (telefono or "").strip()[:40],
        "attempts": 0,
        "sent_at": now_ts,
        "expires_at": now_ts + OTP_TTL_SEC,
    }
    _otp_save(data)

    cuerpo = f"""
      <p>Hola <b>{html_esc((nombre or "").strip() or "ahí")}</b>,</p>
      <p>Tu código para probar el <b>ERP Agrícola DEMO</b> es:</p>
      <p style="font-size:28px;font-weight:800;letter-spacing:.2em;color:#0F4C5C;">{html_esc(code)}</p>
      <p>Válido por 15 minutos. Si no pediste este acceso, ignora el correo.</p>
    """
    html = plantilla_correo_html(
        "acceso",
        "Código de verificación",
        cuerpo,
        nombre_erp="DEMO Agrícola",
    )
    if not _smtp_send(
        secrets_path,
        to=email_n,
        subject="Tu código para probar ERP Agrícola",
        html=html,
    ):
        return False, "No se pudo enviar el código (revise SMTP).", None

    return (
        True,
        "Te enviamos un código a tu correo.",
        {
            "email": email_n,
            "nombre": (nombre or "").strip()[:120],
            "telefono": (telefono or "").strip()[:40],
            "resend_wait": OTP_RESEND_COOLDOWN_SEC,
        },
    )


def validar_codigo_probar(email: str, codigo: str) -> tuple[bool, str, dict | None]:
    email_n = (email or "").strip().lower()
    code = (codigo or "").strip()
    if not email_n or not code:
        return False, "Ingresa el código de 6 dígitos.", None
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
        return False, "Se agotaron los intentos. Solicita un código nuevo.", None
    if _otp_hash(code, entry.get("salt") or "") != entry.get("hash"):
        entry["attempts"] = attempts + 1
        data[email_n] = entry
        _otp_save(data)
        left = OTP_MAX_ATTEMPTS - entry["attempts"]
        if left <= 0:
            data.pop(email_n, None)
            _otp_save(data)
            return False, "Se agotaron los intentos. Solicita un código nuevo.", None
        return False, f"Código incorrecto. Te quedan {left} intento(s).", {
            "email": email_n,
            "nombre": entry.get("nombre") or "",
            "telefono": entry.get("telefono") or "",
        }
    payload = {
        "email": email_n,
        "nombre": entry.get("nombre") or "",
        "telefono": entry.get("telefono") or "",
    }
    data.pop(email_n, None)
    _otp_save(data)
    return True, "Código válido.", payload


def crear_usuario_demo(
    *,
    db_path: str,
    email: str,
    nombre: str,
    telefono: str,
    dias: int = DEMO_DIAS_PRUEBA,
    clave: str = CLAVE_DEMO,
) -> tuple[bool, str, str]:
    """Crea/renueva usuario DEMO. Devuelve (ok, msg, fecha_expira)."""
    email_n = (email or "").strip().lower()
    if not db_path or not os.path.isfile(db_path):
        return False, "Demo no disponible.", ""
    pwd = hash_password(clave)
    exp = fecha_fin_prueba(dias)
    invitado = f"ig:{(telefono or '').strip()}"[:80]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, fecha_expira FROM usuarios WHERE lower(email)=lower(?)",
            (email_n,),
        ).fetchone()
        if row:
            prev = (row["fecha_expira"] or "")[:10]
            exp_use = exp if not usuario_prueba_vigente(prev) else (prev or exp)
            conn.execute(
                """
                UPDATE usuarios
                   SET password=?, rol=?, fecha_expira=?, invitado_por=?
                 WHERE id=?
                """,
                (pwd, ROL_DEMO, exp_use, invitado, row["id"]),
            )
            exp = exp_use
        else:
            conn.execute(
                """
                INSERT INTO usuarios (email, password, rol, fecha_expira, invitado_por, modulos)
                VALUES (?, ?, ?, ?, ?, '')
                """,
                (email_n, pwd, ROL_DEMO, exp, invitado),
            )
        conn.commit()
    finally:
        conn.close()
    return True, "Usuario listo.", exp


def append_lead(row: dict[str, Any]) -> None:
    path = os.path.join(_status_dir(), LEADS_NAME)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def enviar_correo_acceso(
    *,
    secrets_path: str,
    email: str,
    password_plain: str,
    fecha_expira: str,
    dias: int,
    login_url: str,
) -> bool:
    from erp_correo_html import html_esc, plantilla_correo_html

    try:
        ftxt = date.fromisoformat(fecha_expira[:10]).strftime("%d-%m-%Y")
    except Exception:
        ftxt = fecha_expira
    cuerpo = f"""
      <p>Tu acceso al <b>ERP Agrícola DEMO</b> quedó listo.</p>
      <p>
        <b>Usuario:</b> {html_esc(email)}<br>
        <b>Clave:</b> {html_esc(password_plain)}<br>
        <b>Vigente hasta:</b> {html_esc(ftxt)} ({int(dias)} días)
      </p>
      <p><a href="{html_esc(login_url)}" style="display:inline-block;padding:10px 16px;background:#0F4C5C;color:#fff;border-radius:8px;text-decoration:none;font-weight:700;">Entrar al DEMO</a></p>
    """
    html = plantilla_correo_html(
        "acceso",
        "Acceso DEMO Agrícola",
        cuerpo,
        nombre_erp="DEMO Agrícola",
    )
    return _smtp_send(
        secrets_path,
        to=email,
        subject="Tu acceso ERP Agrícola DEMO",
        html=html,
    )
