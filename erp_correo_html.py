"""Plantillas HTML de correos del ERP."""
from __future__ import annotations

from email.headerregistry import Address

SMTP_NOMBRE_REMITENTE = "ERPMASTER"

ALERTA_ACCESO_EXCLUIDOS = frozenset({
    "osvaldolirac@gmail.com",
    "osvaldolira@laconcepcion.cl",
    "osvaldolira@constructorariomaipo.cl",
    "demo@erpmaster.cl",
    "certificacion@erpmaster.cl",
})


def omitir_alerta_acceso(usuario: str | None) -> bool:
    """True si no se debe enviar mail de alerta de acceso para este usuario."""
    return (usuario or "").strip().lower() in ALERTA_ACCESO_EXCLUIDOS


def _alerta_acceso_cooldown(
    usuario: str | None,
    *,
    minutos: int,
    scope: str,
    archivo: str,
) -> bool:
    """True si aún está en cooldown (no enviar). False = permitido y marca timestamp."""
    import json
    import os
    import time

    u = (usuario or "desconocido").strip().lower() or "desconocido"
    s = (scope or "global").strip().lower() or "global"
    key = f"{s}|{u}"
    status_dir = (os.environ.get("ERP_STATUS_DIR") or "/root/erp_status").strip() or "/root/erp_status"
    try:
        os.makedirs(status_dir, exist_ok=True)
    except Exception:
        status_dir = "/tmp"
    path = os.path.join(status_dir, archivo)
    now = time.time()
    data: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
            data = raw if isinstance(raw, dict) else {}
    except Exception:
        data = {}
    last = float(data.get(key) or 0)
    if last and (now - last) < max(60, int(minutos) * 60):
        return True
    data[key] = now
    data = {
        k: v
        for k, v in data.items()
        if isinstance(v, (int, float)) and (now - float(v)) < 86400 * 2
    }
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception:
        pass
    return False


def alerta_acceso_fallo_en_cooldown(
    usuario: str | None,
    *,
    minutos: int = 15,
    scope: str = "global",
) -> bool:
    """Evita spam: 1 mail de acceso RECHAZADO por usuario+scope cada N minutos."""
    return _alerta_acceso_cooldown(
        usuario,
        minutos=minutos,
        scope=scope,
        archivo="alerta_acceso_fallo_cooldown.json",
    )


def alerta_acceso_ok_en_cooldown(
    usuario: str | None,
    *,
    minutos: int = 360,
    scope: str = "global",
) -> bool:
    """Evita spam: 1 mail de ingreso EXITOSO por usuario+scope cada N minutos (default 6 h)."""
    return _alerta_acceso_cooldown(
        usuario,
        minutos=minutos,
        scope=scope,
        archivo="alerta_acceso_ok_cooldown.json",
    )


# Agrícola / plataforma (verde, azul, púrpura clásicos)
TEMAS_CORREO = {
    "invitacion": {"color": "#6A1B9A", "claro": "#F3E5F5"},
    "alerta_ingreso_ok": {"color": "#1B5E20", "claro": "#E8F5E9"},
    "alerta_ingreso_fallo": {"color": "#C62828", "claro": "#FFEBEE"},
    "vencimiento": {"color": "#E65100", "claro": "#FFF3E0"},
    "notificacion_admin": {"color": "#37474F", "claro": "#ECEFF1"},
    "respaldo_datos": {"color": "#0D47A1", "claro": "#E3F2FD"},
    "respaldo_codigo": {"color": "#4A148C", "claro": "#EDE7F6"},
    "ticket_nuevo": {"color": "#1565C0", "claro": "#E3F2FD"},
    "ticket_respuesta": {"color": "#2E7D32", "claro": "#E8F5E9"},
    "alerta_pago": {"color": "#0D47A1", "claro": "#E3F2FD"},
    "alerta_abono": {"color": "#1565C0", "claro": "#E3F2FD"},
}

# Comercial: misma estructura, matices cyan/teal para identificación rápida
TEMAS_COMERCIAL = {
    "alerta_ingreso_ok": {"color": "#0B6A7C", "claro": "#E0F7FA"},
    "alerta_ingreso_fallo": {"color": "#AD1457", "claro": "#FCE4EC"},
    "respaldo_datos": {"color": "#00695C", "claro": "#E0F2F1"},
    "respaldo_codigo": {"color": "#00838F", "claro": "#E0F7FA"},
    "notificacion_admin": {"color": "#0F4C5C", "claro": "#E0F7FA"},
    "alerta_pago": {"color": "#00695C", "claro": "#E0F2F1"},
    "alerta_abono": {"color": "#0F8FA8", "claro": "#E0F7FA"},
    "ticket_nuevo": {"color": "#0F8FA8", "claro": "#E0F7FA"},
    "ticket_respuesta": {"color": "#00695C", "claro": "#E0F2F1"},
    "soporte_nuevo": {"color": "#0F8FA8", "claro": "#E0F7FA"},
    "soporte_respuesta": {"color": "#00695C", "claro": "#E0F2F1"},
}

_NOMBRES_COMERCIAL = {
    "río maipo",
    "rio maipo",
    "comercial lc",
    "comercial",
    "demo comercial",
    "codigo comercial",
    "código comercial",
}


def producto_correo(nombre_erp: str | None = None, producto: str | None = None) -> str:
    p = (producto or "").strip().lower()
    if p == "comercial":
        return "comercial"
    if p == "agricola":
        return "agricola"
    n = (nombre_erp or "").strip().lower()
    if n in _NOMBRES_COMERCIAL or n.startswith("comercial"):
        return "comercial"
    # "Codigo Comercial", "Respaldo Río Maipo", etc.
    if "comercial" in n or "maipo" in n:
        return "comercial"
    return "agricola"


def etiqueta_badge_correo(nombre_erp: str | None = None, producto: str | None = None) -> str:
    """Texto del pill superior: tenant agrícola (ej. AGRÍCOLA LA CONCEPCIÓN) o COMERCIAL."""
    prod = producto_correo(nombre_erp, producto)
    if prod == "comercial":
        return "COMERCIAL"
    n = (nombre_erp or "").strip()
    if not n or n.upper() in {"ERPMASTER", "ERP MASTER", "ERP AGRÍCOLA", "ERP AGRICOLA"}:
        return "ERP AGRÍCOLA"
    u = n.upper()
    if u.startswith("ERP "):
        u = u[4:].strip()
    return u or "ERP AGRÍCOLA"


def smtp_from_header(correo, nombre=None):
    """Remitente visible: ERPMASTER <correo@dominio>."""
    correo = (correo or "").strip()
    nombre = (nombre or SMTP_NOMBRE_REMITENTE).strip()
    if "@" not in correo:
        return correo
    user, domain = correo.rsplit("@", 1)
    return str(Address(display_name=nombre, username=user, domain=domain))


def html_esc(txt):
    return (txt or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plantilla_correo_html(
    tipo,
    titulo,
    cuerpo_interior,
    nombre_erp=None,
    pie=None,
    producto=None,
):
    """Plantilla HTML con banda y título según tipo de correo.

    Si producto/nombre es Comercial, usa matices cyan/teal manteniendo el layout.
    """
    prod = producto_correo(nombre_erp, producto)
    base = TEMAS_CORREO.get(tipo, {"color": "#1B5E20", "claro": "#E8F5E9"})
    if prod == "comercial":
        tema = {**base, **TEMAS_COMERCIAL.get(tipo, {"color": "#0F8FA8", "claro": "#E0F7FA"})}
        badge_bg, badge_fg, badge_txt = "#0F8FA8", "#E0F7FA", etiqueta_badge_correo(nombre_erp, producto)
        fondo = "#eef6f7"
    else:
        tema = base
        badge_bg, badge_fg, badge_txt = "#1B5E20", "#E8F5E9", etiqueta_badge_correo(nombre_erp, producto)
        fondo = "#f4f7f6"
    color = tema["color"]
    claro = tema["claro"]
    titulo_s = html_esc(titulo)
    erp_bloque = ""
    if nombre_erp:
        erp_bloque = (
            f'<p style="margin:0 0 14px;font-size:13px;color:#5F6B7A;">'
            f"<b>Sistema:</b> {html_esc(nombre_erp)}</p>"
        )
    badge = (
        f'<div style="margin:0 0 14px;">'
        f'<span style="display:inline-block;padding:4px 10px;border-radius:4px;'
        f"font-size:11px;font-weight:800;letter-spacing:.10em;"
        f'background:{badge_bg};color:{badge_fg};">{badge_txt}</span></div>'
    )
    pie_txt = html_esc(pie or "Mensaje automático del ERP.")
    return f"""
    <html><body style="font-family:sans-serif;padding:20px;background:{fondo};">
        <div style="background:white;border-radius:10px;box-shadow:0 4px 6px rgba(0,0,0,0.08);padding:24px;border-top:4px solid {color};">
            <div style="height:5px;border-radius:6px;margin:0 0 18px;background:linear-gradient(90deg,{color},{claro});"></div>
            {badge}
            <h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:{color};line-height:1.3;">{titulo_s}</h2>
            {erp_bloque}
            {cuerpo_interior}
            <hr style="border:0;border-top:1px solid #eee;margin:22px 0 14px;">
            <small style="color:#888;">{pie_txt}</small>
        </div>
    </body></html>
    """
