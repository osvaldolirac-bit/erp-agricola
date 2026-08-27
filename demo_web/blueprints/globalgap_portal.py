"""Portal dedicado GlobalGAP consultor: /agricola/globalgap/"""
from __future__ import annotations

import hashlib

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from demo_web.auth.login_next import pop_login_next, safe_next
from demo_web.auth.routes import _activate_session, _maybe_alert_login
from demo_web.auth.user_db import fetch_login_row
from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import bind_tenant_context, get_erp_module_for
from demo_web.services.gap_consultor import (
    create_ambito,
    create_etiqueta,
    migrar_gap_consultor,
    panel_resumen,
)
from demo_web.services.gap_scope import clear_session_ambito, is_globalgap_tenant, set_session_ambito
from demo_web.tenants import get_tenant

TENANT_SLUG = "globalgap"

bp = Blueprint("globalgap_portal", __name__, url_prefix="/globalgap")

_REMEMBER_KEY = "erp_login_remember_globalgap"


def _require_globalgap_tenant(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("tenant_slug") != TENANT_SLUG:
            return redirect(url_for("globalgap_portal.login"))
        return view(*args, **kwargs)

    return wrapped


def _hash_password(password: str) -> str:
    bind_tenant_context(TENANT_SLUG)
    erp = get_erp_module_for(TENANT_SLUG)
    return erp.hash_password(password)


@bp.route("/")
def root():
    if session.get("tenant_slug") == TENANT_SLUG and session.get("email"):
        return redirect(url_for("globalgap_portal.panel"))
    return redirect(url_for("globalgap_portal.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    tenant = get_tenant(TENANT_SLUG)
    if not tenant:
        flash("Tenant GlobalGAP no configurado.", "danger")
        return redirect(url_for("auth.login"))

    if session.get("tenant_slug") == TENANT_SLUG and session.get("email"):
        return redirect(url_for("globalgap_portal.panel"))

    if session.get("tenant_slug") and session.get("tenant_slug") != TENANT_SLUG:
        session.clear()

    error = None
    open_panel = False
    acceso_pref = (request.args.get("acceso") or "").strip()

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        bind_tenant_context(TENANT_SLUG)
        conn = get_erp_module_for(TENANT_SLUG).conectar_db()
        try:
            row = fetch_login_row(conn, email, _hash_password(password))
        finally:
            conn.close()
        if not row:
            error = "Acceso denegado."
            open_panel = True
            flash(error, "danger")
        else:
            _maybe_alert_login(email=email, exitoso=True, tenant_slug=TENANT_SLUG)
            _activate_session(email=row[0], rol=row[1], tenant_slug=TENANT_SLUG)
            clear_session_ambito()
            nxt = pop_login_next()
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("globalgap_portal.panel"))
    elif acceso_pref and "@" in acceso_pref:
        open_panel = True

    return render_template(
        "globalgap_portal/login.html",
        error=error,
        open_panel=open_panel,
        acceso_pref=acceso_pref,
        remember_key=_REMEMBER_KEY,
    )


@bp.route("/login/master")
def master_entry():
    """Puente Super Consola → portal GlobalGAP (/agricola/globalgap/login/master)."""
    from demo_web.auth.routes import master_entry as auth_master_entry

    return auth_master_entry()


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("globalgap_portal.login"))


@bp.route("/panel", methods=["GET", "POST"])
@_require_globalgap_tenant
def panel():
    demo = get_demo_module()
    bind_user_session(session["email"], session.get("rol") or "admin")
    conn = demo.conectar_db()
    try:
        migrar_gap_consultor(conn)
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "crear_etiqueta":
                ok, msg, _ = create_etiqueta(
                    conn,
                    request.form.get("nombre") or "",
                    request.form.get("notas") or "",
                )
                flash(msg, "success" if ok else "danger")
            elif action == "crear_ambito":
                try:
                    eid = int(request.form.get("etiqueta_id") or 0)
                except ValueError:
                    eid = 0
                ok, msg, _ = create_ambito(
                    conn,
                    etiqueta_id=eid,
                    nombre_huerto=request.form.get("nombre_huerto") or "",
                    especie_cultivo=request.form.get("especie_cultivo") or "",
                    plantilla_docs=request.form.get("plantilla_docs") or "cerezos",
                    razon_social=request.form.get("razon_social") or "",
                    direccion=request.form.get("direccion") or "",
                )
                flash(msg, "success" if ok else "danger")
            return redirect(url_for("globalgap_portal.panel"))

        resumen = panel_resumen(conn)
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/panel.html",
        page_title="Panel consultor GlobalGAP",
        resumen=resumen,
        plantillas=("cerezos", "ciruelos"),
    )


@bp.route("/ambito/<int:ambito_id>")
@_require_globalgap_tenant
def entrar_ambito(ambito_id: int):
    demo = get_demo_module()
    bind_user_session(session["email"], session.get("rol") or "admin")
    conn = demo.conectar_db()
    try:
        migrar_gap_consultor(conn)
        from demo_web.services.gap_consultor import get_ambito

        if not get_ambito(conn, ambito_id):
            flash("Ámbito no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.panel"))
    finally:
        conn.close()
    set_session_ambito(ambito_id)
    return redirect(url_for("modules.globalgap"))


def default_landing_for_globalgap():
    if is_globalgap_tenant() and session.get("email"):
        if session.get("gap_ambito_id"):
            return url_for("modules.globalgap")
        return url_for("globalgap_portal.panel")
    return None
