from __future__ import annotations

import os

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from demo_web.auth.user_db import fetch_login_row
from demo_web.services.demo_loader import get_demo_module

bp = Blueprint("auth", __name__)


def _remember_storage_key(db_path: str) -> str:
    slug = os.path.basename(str(db_path or "erp")).replace(".", "_")
    return f"erp_login_remember_{slug}"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("email"):
        return redirect(url_for("modules.dashboard"))
    demo = get_demo_module()
    error = None
    open_panel = False
    remember_key = _remember_storage_key(demo.NOMBRE_DB)
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        conn = demo.conectar_db()
        try:
            row = fetch_login_row(conn, email, demo.hash_password(password))
        finally:
            conn.close()
        if row and demo.usuario_prueba_vigente(row[2]):
            if email.lower() != "osvaldolira@laconcepcion.cl":
                demo.enviar_correo_alerta(email, exitoso=True)
            session.clear()
            session["email"] = row[0]
            session["rol"] = demo.normalizar_rol_usuario(row[1], row[0])
            session.permanent = False
            try:
                from demo_web.services.mantenimiento import slug_for_app, stamp_session_epoch

                slug = slug_for_app(current_app.config.get("ERP_APP", ""))
                if slug:
                    stamp_session_epoch(slug)
            except Exception:
                pass
            nxt = (request.args.get("next") or "").strip()
            prefix = (
                (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
                or (request.environ.get("SCRIPT_NAME") or "").rstrip("/")
                or (current_app.config.get("APPLICATION_ROOT") or "").rstrip("/")
            )
            # next solo dentro del mismo ERP (evita saltar a /riomaipo u otros)
            if (
                not nxt
                or not nxt.startswith("/")
                or nxt.startswith("//")
                or "://" in nxt
                or nxt.startswith("/riomaipo")
                or (prefix == "/demo" and nxt.startswith("/laconcepcion"))
                or (prefix == "/laconcepcion" and nxt.startswith("/demo"))
                or (prefix and not (nxt == prefix or nxt.startswith(prefix + "/")))
            ):
                nxt = url_for("modules.dashboard")
            return redirect(nxt)
        demo.enviar_correo_alerta(email or "desconocido", exitoso=False)
        error = "Acceso denegado o periodo de prueba vencido."
        open_panel = True
        flash(error, "danger")
    return render_template(
        "login.html",
        error=error,
        open_panel=open_panel,
        demo_url=demo.DEMO_URL,
        remember_key=remember_key,
    )


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
