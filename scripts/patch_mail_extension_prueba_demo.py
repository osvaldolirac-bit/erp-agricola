#!/usr/bin/env python3
"""Inserta enviar_correo_extension_prueba_demo en app_demo.py (VPS/demo-web)."""
from __future__ import annotations

from pathlib import Path

TARGET = Path("/root/demo-web/app_demo.py")

NEW_FN = '''
def enviar_correo_extension_prueba_demo(email_usuario, rol, admin_email, fecha_expira, dias_agregados, fecha_anterior=""):
    """Avisa extensión de prueba al usuario y copia al correo_receptor (mail respaldo)."""
    from erp_correo_html import plantilla_correo_html

    f_h = hora_chile().strftime("%d-%m-%Y %H:%M")
    f_exp = pd.to_datetime(fecha_expira).strftime("%d-%m-%Y")
    try:
        d = max(1, int(dias_agregados or 0))
    except (TypeError, ValueError):
        d = 0
    perfil_txt = etiqueta_perfil_demo(rol, email_usuario)
    ant_txt = ""
    if fecha_anterior:
        try:
            ant_txt = pd.to_datetime(fecha_anterior).strftime("%d-%m-%Y")
        except Exception:
            ant_txt = str(fecha_anterior)[:10]
    linea_ant = (
        f"<p style='margin: 8px 0 0; color: #5D4037;'>Fecha anterior: <b>{ant_txt}</b></p>"
        if ant_txt else ""
    )
    interior = f"""
            <p style='color: #1F2933; line-height: 1.55;'>
                Se ha <b>extendido el periodo de prueba</b> de su acceso al
                <b>ERP Agrícola (demo)</b>.
            </p>
            <div style='background: #E8F5E9; border: 1px solid #A5D6A7; border-radius: 10px; padding: 14px 18px; margin: 18px 0;'>
                <p style='margin: 0; color: #1B5E20; font-weight: 700;'>✅ Extensión: +{d} día{"s" if d != 1 else ""}</p>
                <p style='margin: 8px 0 0; color: #1B5E20;'>Nueva vigencia hasta el <b>{f_exp}</b> (inclusive).</p>
                {linea_ant}
                <p style='margin: 8px 0 0; color: #1B5E20;'>Recibirá avisos automáticos por correo <b>24 horas antes</b> y <b>al vencer el plazo</b>.</p>
            </div>
            <div style='background: #F3E5F5; border: 1px solid #CE93D8; border-radius: 10px; padding: 18px 20px; margin: 18px 0;'>
                <p style='margin: 0 0 10px; font-weight: 800; color: #6A1B9A;'>📋 Datos de acceso</p>
                <p style='margin: 6px 0;'><b>Usuario:</b> <span style='color: #6A1B9A; font-weight: bold;'>{email_usuario}</span></p>
                <p style='margin: 6px 0;'><b>Perfil:</b> {perfil_txt}</p>
                <p style='margin: 6px 0;'><b>Enlace:</b> <a href='{DEMO_URL}' style='color: #6A1B9A; font-weight: bold;'>{DEMO_URL}</a></p>
            </div>
            <p style='text-align: center; margin: 24px 0;'>
                <a href='{DEMO_URL}' style='display: inline-block; background: linear-gradient(135deg, #6A1B9A, #9C27B0); color: white; text-decoration: none; padding: 12px 28px; border-radius: 10px; font-weight: 800;'>ACCEDER AL ERP DEMO</a>
            </p>
            <p style='font-size: 13px; color: #5F6B7A; margin: 6px 0;'><b>Extensión emitida por:</b> {admin_email or 'Administrador ERP Demo'}</p>
            <p style='font-size: 13px; color: #5F6B7A; margin: 6px 0;'><b>Fecha:</b> {f_h} (Chile UTC-4)</p>
    """
    cuerpo = plantilla_correo_html(
        "invitacion",
        "🚜 Prueba extendida — ERP Agrícola Demo",
        interior,
        nombre_erp="ERP DEMO AGRICOLA",
        pie="Si no esperaba este aviso, ignore el correo.",
    )
    cc_respaldo = _destinatarios_admin_demo(admin_email)
    cc_respaldo = [c for c in cc_respaldo if c.lower() != str(email_usuario or "").strip().lower()]
    ok_usuario = _enviar_correo_html(
        f"🚜 Prueba extendida — ERP Agrícola Demo (+{d} días, hasta {f_exp})",
        cuerpo,
        [email_usuario],
    )
    _registrar_envio_correo("MAIL EXTENSION PRUEBA", email_usuario, ok_usuario)
    ok_copia = True
    if cc_respaldo:
        asunto_copia = f"📋 Copia — Prueba extendida para {email_usuario}"
        if not ok_usuario:
            asunto_copia += " (falló envío al usuario)"
        ok_copia = _enviar_correo_html(asunto_copia, cuerpo, cc_respaldo)
        _registrar_envio_correo("MAIL EXTENSION PRUEBA COPIA", cc_respaldo, ok_copia)
    return {"usuario": ok_usuario, "copia": ok_copia}

'''


def main() -> int:
    t = TARGET.read_text(encoding="utf-8")
    if "def enviar_correo_extension_prueba_demo" in t:
        print("OK already present")
        return 0
    anchor = "\ndef anclaje_sesion_definitivo():"
    idx = t.find(anchor)
    if idx < 0:
        print("ERROR: anchor not found")
        return 1
    TARGET.write_text(t[:idx] + "\n" + NEW_FN + t[idx:], encoding="utf-8")
    print("OK patched", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
