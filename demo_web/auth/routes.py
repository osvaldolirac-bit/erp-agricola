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

from demo_web.auth.decorators import login_required
from demo_web.auth.login_next import default_landing_url, pop_login_next, safe_next, stash_login_next
from demo_web.auth.tenant_access import list_accessible_tenants, tenant_access_option
from demo_web.auth.user_db import fetch_bridge_user, fetch_login_row
from demo_web.services.erp_loader import bind_tenant_context, get_erp_module_for, invalidate_erp_module
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
    accessible_tenants: list[dict] | None = None,
) -> None:
    bind_tenant_context(tenant_slug)
    erp = get_erp_module_for(tenant_slug)
    preserved_tenants = accessible_tenants or session.get("accessible_tenants")
    session.clear()
    invalidate_erp_module()
    session["email"] = email
    session["rol"] = erp.normalizar_rol_usuario(rol, email) if hasattr(erp, "normalizar_rol_usuario") else rol
    session["tenant_slug"] = tenant_slug
    session["accessible_tenants"] = preserved_tenants or list_accessible_tenants(email)
    if from_master:
        session["from_master_console"] = True
    elif tenant_slug == "demo":
        try:
            from demo_web.master_bitacora import log_master_bitacora

            log_master_bitacora(tenant_slug, email, "INGRESO_ERP", "Ingreso al ERP Agrícola DEMO")
        except Exception:
            pass
    session.permanent = False
    try:
        from demo_web.services.mantenimiento import (
            clear_post_mantenimiento,
            stamp_session_epoch,
        )

        stamp_session_epoch(tenant_slug)
        clear_post_mantenimiento(tenant_slug)
    except Exception:
        pass


def _maybe_alert_login(*, email: str, exitoso: bool, tenant_slug: str | None = None) -> None:
    """Alerta SMTP de ingreso — sin spam en DEMO público ni cuentas internas."""
    em = (email or "").strip().lower()
    slug = (tenant_slug or "").strip().lower()
    if slug == "demo":
        return
    try:
        from erp_correo_html import omitir_alerta_acceso

        if omitir_alerta_acceso(em):
            return
    except Exception:
        if em in {
            "demo@erpmaster.cl",
            "certificacion@erpmaster.cl",
            "osvaldolira@laconcepcion.cl",
            "osvaldolirac@gmail.com",
        }:
            return
    if not exitoso:
        return
    try:
        mod = get_erp_module_for(slug or "concepcion")
        mod.enviar_correo_alerta(email or "desconocido", exitoso=True)
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
    return redirect(default_landing_url())


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("email") and session.get("tenant_slug"):
        return redirect(safe_next(pop_login_next()))

    # URL limpia: destino post-login en sesión, no en ?next=
    if request.method == "GET" and request.args.get("next"):
        stash_login_next(request.args.get("next"))
        return redirect(url_for("auth.login"))

    error = None
    open_panel = False
    remember_key = _remember_storage_key()
    acceso_pref = (request.args.get("acceso") or "").strip()
    if acceso_pref and "@" in acceso_pref:
        open_panel = True

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        matches = _find_login_matches(email, password)
        if not matches:
            error = "Acceso denegado o periodo de prueba vencido."
            open_panel = True
            flash(error, "danger")
            try:
                from demo_web.master_bitacora import log_master_bitacora

                log_master_bitacora(
                    "demo",
                    email or "desconocido",
                    "INGRESO_FALLIDO",
                    "Intento de acceso rechazado",
                )
            except Exception:
                pass
        elif len(matches) == 1:
            m = matches[0]
            _maybe_alert_login(email=email, exitoso=True, tenant_slug=m["slug"])
            _activate_session(
                email=m["email"],
                rol=m["rol"],
                tenant_slug=m["slug"],
                accessible_tenants=matches,
            )
            return redirect(safe_next(pop_login_next()))
        else:
            # Varios tenants: selector
            options = [
                {
                    "slug": m["slug"],
                    "nombre": m["nombre"],
                    "descripcion": m["descripcion"],
                    "rol": m["rol"],
                }
                for m in matches
            ]
            session["pending_login"] = {
                "email": matches[0]["email"],
                "options": options,
            }
            return redirect(url_for("auth.elegir_empresa"))

    return render_template(
        "login.html",
        error=error,
        open_panel=open_panel,
        remember_key=remember_key,
        acceso_pref=acceso_pref,
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
        _activate_session(
            email=email,
            rol=chosen.get("rol") or "operador",
            tenant_slug=slug,
            accessible_tenants=options,
        )
        session.pop("pending_login", None)
        return redirect(safe_next(pop_login_next()))

    return render_template(
        "select_tenant.html",
        email=email,
        options=options,
    )


@bp.route("/auth/cambiar-empresa", methods=["POST"])
@login_required
def cambiar_empresa():
    email = (session.get("email") or "").strip()
    slug = (request.form.get("tenant_slug") or "").strip().lower()
    current = (session.get("tenant_slug") or "").strip().lower()
    if not email or not slug:
        flash("No se pudo cambiar de empresa.", "warning")
        return redirect(default_landing_url())
    if slug == current:
        return redirect(default_landing_url())

    try:
        from demo_web.services.mantenimiento import en_mantenimiento

        if en_mantenimiento(slug):
            flash("Ese ERP está en mantención. Intenta más tarde.", "warning")
            return redirect(default_landing_url())
    except Exception:
        pass

    chosen = tenant_access_option(email, slug)
    if not chosen:
        flash("No tienes acceso a esa empresa.", "danger")
        return redirect(default_landing_url())

    accessible = session.get("accessible_tenants") or list_accessible_tenants(email)
    _activate_session(
        email=email,
        rol=chosen["rol"],
        tenant_slug=slug,
        accessible_tenants=accessible,
    )
    try:
        from demo_web.services.mantenimiento import bitacora_erp_activa

        if bitacora_erp_activa(slug):
            erp = get_erp_module_for(slug)
            erp.registrar_accion(
                "CAMBIO EMPRESA",
                f"{current or '—'} → {slug} ({email})",
            )
    except Exception:
        pass
    flash(f"Ahora estás en {chosen['nombre']}.", "info")
    return redirect(url_for("modules.dashboard"))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
