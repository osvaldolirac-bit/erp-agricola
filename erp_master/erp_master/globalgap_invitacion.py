"""Invitación de prueba del consultor GlobalGAP.

La clave viaja solo en el correo del invitado. La copia al quien invita
no la repite.
"""
from __future__ import annotations

import html
from datetime import date, timedelta

GLOBALGAP_LOGIN_URL = "https://erpmaster.cl/agricola/globalgap/login"


def fecha_fin_prueba(hoy: date, dias: int) -> str:
    return (hoy + timedelta(days=max(1, int(dias)))).isoformat()


def copias_sin_clave(admin_email: str, invitado: str, extras: list[str] | None = None) -> list[str]:
    """Correos que reciben la copia, sin el invitado y sin duplicados."""
    vistos: set[str] = set()
    salida: list[str] = []
    inv = (invitado or "").strip().lower()
    for raw in [admin_email, *(extras or [])]:
        correo = str(raw or "").strip()
        clave = correo.lower()
        if not correo or "@" not in correo or clave == inv or clave in vistos:
            continue
        vistos.add(clave)
        salida.append(correo)
    return salida


def _fecha_visible(fecha_expira: str) -> str:
    try:
        return date.fromisoformat(str(fecha_expira)[:10]).strftime("%d-%m-%Y")
    except ValueError:
        return str(fecha_expira or "")[:10]


def cuerpo_invitacion_globalgap(
    *,
    email: str,
    rol_txt: str,
    fecha_expira: str,
    admin_email: str,
    clave: str = "",
    para_copia: bool = False,
) -> str:
    """HTML de la invitación. Con clave vacía el cuerpo no trae contraseña."""
    email_s = html.escape(email)
    rol_s = html.escape(rol_txt or "admin")
    fecha_s = html.escape(_fecha_visible(fecha_expira))
    url_s = html.escape(GLOBALGAP_LOGIN_URL, quote=True)
    admin_s = html.escape(admin_email or "Administrador")
    if clave and not para_copia:
        bloque_clave = (
            "<p style='margin: 6px 0;'><b>Contraseña:</b> "
            f"<span style='color: #1B5E20; font-weight: bold;'>{html.escape(clave)}</span></p>"
        )
        intro = (
            "Has sido invitado al <b>consultor GlobalGAP</b>. "
            "Este acceso es de prueba."
        )
    elif para_copia:
        bloque_clave = (
            "<p style='margin: 6px 0; color: #5F6B7A;'>"
            "La contraseña no va en esta copia. "
            "Quedó solo en el correo del invitado, o es la que se escribió en la consola."
            "</p>"
        )
        intro = (
            f"Se envió un acceso de prueba GlobalGAP a <b>{email_s}</b>. "
            "Esta copia no incluye la contraseña."
        )
    else:
        bloque_clave = (
            "<p style='margin: 6px 0; color: #5F6B7A;'>"
            "Use la clave definida al crear la cuenta. Este correo no la repite."
            "</p>"
        )
        intro = (
            "Su acceso al <b>consultor GlobalGAP</b> es de prueba. "
            "El ingreso es el portal del consultor."
        )
    interior = f"""
            <p style='color: #1F2933; line-height: 1.55;'>{intro}</p>
            <div style='background: #E8F5E9; border: 1px solid #A5D6A7; border-radius: 10px; padding: 14px 18px; margin: 18px 0;'>
                <p style='margin: 0; color: #1B5E20; font-weight: 700;'>Periodo de prueba</p>
                <p style='margin: 8px 0 0; color: #1B5E20;'>Vigente hasta el <b>{fecha_s}</b> (inclusive).</p>
            </div>
            <div style='background: #F1F8E9; border: 1px solid #C5E1A5; border-radius: 10px; padding: 18px 20px; margin: 18px 0;'>
                <p style='margin: 0 0 10px; font-weight: 800; color: #33691E;'>Datos de acceso</p>
                <p style='margin: 6px 0;'><b>Usuario:</b> {email_s}</p>
                {bloque_clave}
                <p style='margin: 6px 0;'><b>Perfil:</b> {rol_s}</p>
                <p style='margin: 6px 0;'><b>Enlace:</b> <a href='{url_s}'>{url_s}</a></p>
            </div>
            <p style='font-size: 13px; color: #5F6B7A;'><b>Invitación emitida por:</b> {admin_s}</p>
    """
    try:
        from erp_correo_html import plantilla_correo_html

        return plantilla_correo_html(
            "invitacion",
            "Bienvenido al consultor GlobalGAP",
            interior,
            nombre_erp="GLOBALGAP CONSULTOR",
            pie="Si no esperaba esta invitación, ignore el correo.",
        )
    except Exception:
        return f"<html><body>{interior}</body></html>"


def enviar_invitacion_globalgap(
    *,
    email: str,
    password_plain: str,
    rol: str,
    admin_email: str,
    fecha_expira: str,
    enviar_html,
    copias_extra: list[str] | None = None,
    incluir_clave_al_invitado: bool = True,
) -> tuple[bool, str]:
    """Envía al invitado y una copia sin clave a quien invita.

    enviar_html(asunto, cuerpo, destinatarios) -> bool.
    """
    clave = password_plain if incluir_clave_al_invitado else ""
    if incluir_clave_al_invitado and clave:
        asunto_inv = "Invitación — GlobalGAP Consultor (acceso de prueba)"
        cuerpo_inv = cuerpo_invitacion_globalgap(
            email=email,
            rol_txt=rol,
            fecha_expira=fecha_expira,
            admin_email=admin_email,
            clave=clave,
            para_copia=False,
        )
    else:
        asunto_inv = "GlobalGAP Consultor — su acceso es de prueba"
        cuerpo_inv = cuerpo_invitacion_globalgap(
            email=email,
            rol_txt=rol,
            fecha_expira=fecha_expira,
            admin_email=admin_email,
            clave="",
            para_copia=False,
        )
    ok_inv = bool(enviar_html(asunto_inv, cuerpo_inv, [email]))
    copias = copias_sin_clave(admin_email, email, copias_extra)
    ok_copia = False
    if copias:
        cuerpo_copia = cuerpo_invitacion_globalgap(
            email=email,
            rol_txt=rol,
            fecha_expira=fecha_expira,
            admin_email=admin_email,
            clave="",
            para_copia=True,
        )
        ok_copia = bool(
            enviar_html(
                f"Copia — Invitación GlobalGAP enviada a {email} (sin clave)",
                cuerpo_copia,
                copias,
            )
        )
    dest_copia = ", ".join(copias) if copias else ""
    if ok_inv and ok_copia:
        if clave:
            return True, (
                f"La clave se envió a {email}. La copia sin clave se envió a {dest_copia}."
            )
        return True, f"Se avisó a {email}. La copia sin clave se envió a {dest_copia}."
    if ok_inv and not copias:
        return True, f"Se envió el aviso a {email}. No había otro correo para la copia."
    if ok_inv and not ok_copia:
        return True, f"Se envió el aviso a {email}. La copia de respaldo no salió."
    if ok_copia:
        return True, f"No se pudo avisar a {email}. La copia sin clave sí se envió a {dest_copia}."
    return False, "No se pudo enviar el correo de invitación (revise SMTP)."
