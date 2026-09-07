from __future__ import annotations

from flask import render_template, request

from demo_web.services.modules_data import manual_html


def view(user_email: str, user_rol: str):
    doc = request.args.get("doc", "guia")
    guia, completo, aviso = manual_html(user_email, user_rol)
    return render_template(
        "modules/manual.html",
        page_title="Manual",
        active_key="Manual",
        title="Manual de usuario",
        doc=doc,
        aviso=aviso,
        html=completo if doc == "completo" else guia,
    )
