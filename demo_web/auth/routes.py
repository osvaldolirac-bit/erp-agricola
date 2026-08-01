from __future__ import annotations

import time

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
from demo_web.services.erp_loader import bind_tenant_context, get_erp_module_for
from demo_web.tenants import get_tenant, list_tenants

bp = Blueprint("auth", __name__)

_BRIDGE_SALT = "erp-master-bridge-v1"
_BRIDGE_MAX_AGE = 120


def _remember_storage_key() -> str:
    return "erp_login_remember_agricola"


def _bridge_secret() -> str:
    return (
        (current_app.config.get("MASTER_BRIDGE_SECRET") or "").strip()
        or (os.environ.get("ERP_MASTER_BRIDGE_SECRET") or "").strip()
    )


def _activate_session(
    *,
    email: str,
    rol: str,
    tenant_slug: str,
    from_master: bool = False,
) -> None:
    bind_tenant_context(tenant_slug)
    erp = get_erp_module_for(tenant_slug)
    session.clear()
    session["email"] = email
    session["rol"] = erp.normalizar_rol_usuario(rol, email) if hasattr(erp, "normalizar_rol_usuario") else rol
    session["tenant_slug"] = tenant_slug
    if from_master:
        session["from_master_console"] = True
    session.permanent = False
    session["last_activity"] = time.time()
    try:
        from demo_web.services.mantenimiento import (
            clear_post_mantenimiento,
            stamp_session_epoch,
        )

        stamp_session_epoch(tenant_slug)
        clear_post_mantenimiento(tenant_slug)
    except Exception:
        pass


def _find_login_matches(email: str, password: str) -> list[dict]:
    matches: list[dict] = []
    for t in list_tenants():
        try:
            erp = get_erp_module_for(t["slug"])
            conn = erp.conectar_db()
            try:
                row = fetch_login_row(conn, email, erp.hash_password(password))
            finally:
                conn.close()
            if not row:
                continue
            if not erp.usuario_prueba_vigente(row[2]):
                continue
            rol = erp.normalizar_rol_usuario(row[1], row[0]) if hasattr(erp, "normalizar_rol_usuario") else row[1]
            matches.append(
                {
                    "slug": t["slug"],
                    "nombre": t["nombre"],
                    "descripcion": t.get("descripcion") or "",
                    "email": row[0],
                    "rol": rol,
                }
            )
        except Exception:
            continue
    return matches


def _home_for_rol(rol: str | None = None) -> str:
    """Landing post-login según perfil."""
    r = (rol if rol is not None else session.get("rol") or "").strip().lower()
    if r == "certificacion":
        try:
            return url_for("modules.globalgap")
        except Exception:
            pass
    return url_for("modules.dashboard")


def _safe_next(raw: str | None) -> str:
    nxt = (raw or "").strip()
    prefix = (
        (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
        or (request.environ.get("SCRIPT_NAME") or "").rstrip("/")
        or (current_app.config.get("APPLICATION_ROOT") or "").rstrip("/")
    )
    if (
        not nxt
        or not nxt.startswith("/")
        or nxt.startswith("//")
        or "://" in nxt
        or nxt.startswith("/riomaipo")
        or nxt.startswith("/laconcepcion")
        or nxt.startswith("/demo")
        or (prefix and not (nxt == prefix or nxt.startswith(prefix + "/")))
    ):
        return _home_for_rol()
    return nxt


@bp.route("/login/master")
def master_entry():
    """Ingreso desde Super Consola → tenant del token + dashboard."""
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
    if not email or not get_tenant(token_slug):
        return redirect(url_for("auth.login"))

    # Mantención del tenant destino
    try:
        from demo_web.services.mantenimiento import en_mantenimiento

        if en_mantenimiento(token_slug):
            flash("Ese cliente está en mantención.", "warning")
            return redirect(url_for("auth.login"))
    except Exception:
        pass

    erp = get_erp_module_for(token_slug)
    conn = erp.conectar_db()
    try:
        row = fetch_bridge_user(conn, email)
    finally:
        conn.close()
    if not row:
        flash("Tu usuario de consola no existe en este ERP. Ingresa con tu clave.", "warning")
        return redirect(url_for("auth.login"))
    if not erp.usuario_prueba_vigente(row[2]):
        flash("Su periodo de prueba ha finalizado.", "warning")
        return redirect(url_for("auth.login"))

    _activate_session(
        email=row[0],
        rol=row[1],
        tenant_slug=token_slug,
        from_master=True,
    )
    return redirect(_home_for_rol(row[1]))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("email") and session.get("tenant_slug"):
        return redirect(_home_for_rol())

    error = None
    open_panel = False
    remember_key = _remember_storage_key()

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        matches = _find_login_matches(email, password)
        if not matches:
            # alerta en el primer tenant demo si existe (best-effort)
            try:
                erp = get_erp_module_for("demo")
                erp.enviar_correo_alerta(email or "desconocido", exitoso=False)
            except Exception:
                pass
            error = "Acceso denegado o periodo de prueba vencido."
            open_panel = True
            flash(error, "danger")
        elif len(matches) == 1:
            m = matches[0]
            try:
                get_erp_module_for(m["slug"]).enviar_correo_alerta(email, exitoso=True)
            except Exception:
                pass
            _activate_session(email=m["email"], rol=m["rol"], tenant_slug=m["slug"])
            return redirect(_safe_next(request.args.get("next")))
        else:
            # Varios tenants: selector
            session["pending_login"] = {
                "email": matches[0]["email"],
                "options": [
                    {
                        "slug": m["slug"],
                        "nombre": m["nombre"],
                        "descripcion": m["descripcion"],
                        "rol": m["rol"],
                    }
                    for m in matches
                ],
            }
            return redirect(url_for("auth.elegir_empresa"))

    return render_template(
        "login.html",
        error=error,
        open_panel=open_panel,
        remember_key=remember_key,
    )


@bp.route("/login/empresa", methods=["GET", "POST"])
def elegir_empresa():
    pending = session.get("pending_login") or {}
    options = pending.get("options") or []
    email = pending.get("email") or ""
    if not options or not email:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        slug = (request.form.get("tenant_slug") or "").strip().lower()
        chosen = next((o for o in options if o.get("slug") == slug), None)
        if not chosen or not get_tenant(slug):
            flash("Elige una empresa válida.", "warning")
            return redirect(url_for("auth.elegir_empresa"))
        _activate_session(email=email, rol=chosen.get("rol") or "operador", tenant_slug=slug)
        session.pop("pending_login", None)
        return redirect(_home_for_rol(chosen.get("rol") or "operador"))

    return render_template(
        "select_tenant.html",
        email=email,
        options=options,
    )


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
