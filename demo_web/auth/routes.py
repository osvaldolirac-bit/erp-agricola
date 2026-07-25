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

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from demo_web.auth.user_db import fetch_bridge_user, fetch_login_row
from demo_web.services.demo_loader import get_demo_module

bp = Blueprint("auth", __name__)

_BRIDGE_SALT = "erp-master-bridge-v1"
_BRIDGE_MAX_AGE = 120


def _remember_storage_key(db_path: str) -> str:
    slug = os.path.basename(str(db_path or "erp")).replace(".", "_")
    return f"erp_login_remember_{slug}"


def _bridge_secret() -> str:
    return (
        (current_app.config.get("MASTER_BRIDGE_SECRET") or "").strip()
        or (os.environ.get("ERP_MASTER_BRIDGE_SECRET") or "").strip()
    )


@bp.route("/login/master")
def master_entry():
    """Ingreso desde Super Consola ERP Master → sesión + dashboard."""
    token = (request.args.get("t") or "").strip()
    secret = _bridge_secret()
    if not token or not secret:
        return redirect(url_for("auth.login"))
    try:
        data = URLSafeTimedSerializer(secret, salt=_BRIDGE_SALT).loads(
            token, max_age=_BRIDGE_MAX_AGE
        )
    except SignatureExpired:
        flash("El enlace de acceso expiró. Vuelve a abrir el ERP desde la consola.", "warning")
        return redirect(url_for("auth.login"))
    except BadSignature:
        flash("Enlace de acceso inválido.", "danger")
        return redirect(url_for("auth.login"))

    email = (data.get("email") or "").strip() if isinstance(data, dict) else ""
    token_slug = (data.get("slug") or "").strip().lower() if isinstance(data, dict) else ""
    if not email:
        return redirect(url_for("auth.login"))

    try:
        from demo_web.services.mantenimiento import slug_for_app

        app_slug = slug_for_app(current_app.config.get("ERP_APP", ""))
    except Exception:
        app_slug = ""
    if token_slug and app_slug and token_slug != app_slug:
        flash("El enlace no corresponde a este ERP.", "danger")
        return redirect(url_for("auth.login"))

    demo = get_demo_module()
    conn = demo.conectar_db()
    try:
        row = fetch_bridge_user(conn, email)
    finally:
        conn.close()
    if not row:
        flash("Tu usuario de consola no existe en este ERP. Ingresa con tu clave.", "warning")
        return redirect(url_for("auth.login"))
    if not demo.usuario_prueba_vigente(row[2]):
        flash("Su periodo de prueba ha finalizado.", "warning")
        return redirect(url_for("auth.login"))

    session.clear()
    session["email"] = row[0]
    session["rol"] = demo.normalizar_rol_usuario(row[1], row[0])
    session.permanent = False
    try:
        from demo_web.services.mantenimiento import (
            clear_post_mantenimiento,
            slug_for_app,
            stamp_session_epoch,
        )

        slug = slug_for_app(current_app.config.get("ERP_APP", ""))
        if slug:
            stamp_session_epoch(slug)
            clear_post_mantenimiento(slug)
    except Exception:
        pass
    return redirect(url_for("modules.dashboard"))


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
                from demo_web.services.mantenimiento import (
                    clear_post_mantenimiento,
                    en_post_mantenimiento,
                    slug_for_app,
                    stamp_session_epoch,
                )

                slug = slug_for_app(current_app.config.get("ERP_APP", ""))
                if slug:
                    stamp_session_epoch(slug)
                    # Tras mantención: siempre dashboard (ignora next a módulos viejos).
                    if en_post_mantenimiento(slug):
                        clear_post_mantenimiento(slug)
                        return redirect(url_for("modules.dashboard"))
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
