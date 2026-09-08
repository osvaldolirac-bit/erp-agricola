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
    create_csg,
    create_etiqueta,
    get_csg,
    get_etiqueta,
    list_etiquetas,
    migrar_gap_consultor,
    panel_resumen,
    update_csg,
    update_etiqueta,
)
from demo_web.services.gap_scope import clear_session_ambito, is_globalgap_tenant, set_session_ambito
from demo_web.tenants import get_tenant

TENANT_SLUG = "globalgap"

bp = Blueprint("globalgap_portal", __name__, url_prefix="/globalgap")

_REMEMBER_KEY = "erp_login_remember_globalgap"
_PLANTILLAS = ("cerezos", "ciruelos")


def _require_globalgap_tenant(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("tenant_slug") != TENANT_SLUG:
            return redirect(url_for("globalgap_portal.login"))
        return view(*args, **kwargs)

    return wrapped


def _conn():
    demo = get_demo_module()
    bind_user_session(session["email"], session.get("rol") or "admin")
    return demo.conectar_db()


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


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("globalgap_portal.login"))


@bp.route("/panel")
@_require_globalgap_tenant
def panel():
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        resumen = panel_resumen(conn)
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/panel.html",
        active_key="PanelGlobalGAP",
        body_class="gap-comercial-page",
        page_title="Panel consultor GlobalGAP",
        resumen=resumen,
    )


@bp.route("/clientes/")
@_require_globalgap_tenant
def clientes_list():
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        clientes = list_etiquetas(conn, activos_only=False)
    finally:
        conn.close()
    return render_template(
        "globalgap_portal/clientes/lista.html",
        active_key="ClientesGlobalGAP",
        page_title="Clientes GlobalGAP",
        clientes=clientes,
    )


@bp.route("/clientes/nuevo", methods=["GET", "POST"])
@_require_globalgap_tenant
def clientes_nuevo():
    if request.method == "POST":
        conn = _conn()
        try:
            migrar_gap_consultor(conn)
            ok, msg, eid = create_etiqueta(
                conn,
                request.form.get("nombre") or "",
                request.form.get("notas") or "",
            )
        finally:
            conn.close()
        flash(msg, "success" if ok else "danger")
        if ok and eid:
            return redirect(url_for("globalgap_portal.clientes_detalle", etiqueta_id=eid))
        return redirect(url_for("globalgap_portal.clientes_nuevo"))

    return render_template(
        "globalgap_portal/clientes/form_cliente.html",
        active_key="ClientesGlobalGAP",
        page_title="Nuevo cliente",
        cliente=None,
    )


@bp.route("/clientes/<int:etiqueta_id>")
@_require_globalgap_tenant
def clientes_detalle(etiqueta_id: int):
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        cliente = get_etiqueta(conn, etiqueta_id)
        if not cliente:
            flash("Cliente no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.clientes_list"))
        from demo_web.services.gap_consultor import list_csg

        csgs = list_csg(conn, etiqueta_id, activos_only=False)
        resumen = panel_resumen(conn)
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/clientes/detalle.html",
        active_key="ClientesGlobalGAP",
        page_title=cliente["nombre"],
        cliente=cliente,
        csgs=csgs,
        cards_by_ambito=resumen["cards_by_ambito"],
        plantillas=_PLANTILLAS,
    )


@bp.route("/clientes/<int:etiqueta_id>/editar", methods=["GET", "POST"])
@_require_globalgap_tenant
def clientes_editar(etiqueta_id: int):
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        cliente = get_etiqueta(conn, etiqueta_id)
        if not cliente:
            flash("Cliente no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.clientes_list"))
        if request.method == "POST":
            ok, msg = update_etiqueta(
                conn,
                etiqueta_id,
                nombre=request.form.get("nombre") or "",
                notas=request.form.get("notas") or "",
                activo=bool(request.form.get("activo")),
            )
            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(url_for("globalgap_portal.clientes_detalle", etiqueta_id=etiqueta_id))
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/clientes/form_cliente.html",
        active_key="ClientesGlobalGAP",
        page_title=f"Editar {cliente['nombre']}",
        cliente=cliente,
    )


@bp.route("/clientes/<int:etiqueta_id>/csg/nuevo", methods=["GET", "POST"])
@_require_globalgap_tenant
def csg_nuevo(etiqueta_id: int):
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        cliente = get_etiqueta(conn, etiqueta_id)
        if not cliente:
            flash("Cliente no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.clientes_list"))
        if request.method == "POST":
            ok, msg, cid = create_csg(
                conn,
                etiqueta_id=etiqueta_id,
                codigo_csg=request.form.get("codigo_csg") or "",
                nombre_predio=request.form.get("nombre_predio") or "",
                direccion=request.form.get("direccion") or "",
                comuna=request.form.get("comuna") or "",
                region=request.form.get("region") or "",
                notas=request.form.get("notas") or "",
            )
            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(url_for("globalgap_portal.clientes_detalle", etiqueta_id=etiqueta_id))
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/clientes/form_csg.html",
        active_key="ClientesGlobalGAP",
        page_title=f"Nuevo CSG — {cliente['nombre']}",
        cliente=cliente,
        csg=None,
    )


@bp.route("/clientes/csg/<int:csg_id>/editar", methods=["GET", "POST"])
@_require_globalgap_tenant
def csg_editar(csg_id: int):
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        csg = get_csg(conn, csg_id)
        if not csg:
            flash("CSG no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.clientes_list"))
        cliente = get_etiqueta(conn, csg["etiqueta_id"])
        if request.method == "POST":
            ok, msg = update_csg(
                conn,
                csg_id,
                codigo_csg=request.form.get("codigo_csg") or "",
                nombre_predio=request.form.get("nombre_predio") or "",
                direccion=request.form.get("direccion") or "",
                comuna=request.form.get("comuna") or "",
                region=request.form.get("region") or "",
                notas=request.form.get("notas") or "",
                activo=bool(request.form.get("activo")),
            )
            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(
                    url_for("globalgap_portal.clientes_detalle", etiqueta_id=csg["etiqueta_id"])
                )
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/clientes/form_csg.html",
        active_key="ClientesGlobalGAP",
        page_title=f"Editar CSG {csg['codigo_csg']}",
        cliente=cliente,
        csg=csg,
    )


@bp.route("/clientes/csg/<int:csg_id>/ambitos/nuevo", methods=["GET", "POST"])
@_require_globalgap_tenant
def ambito_nuevo(csg_id: int):
    conn = _conn()
    try:
        migrar_gap_consultor(conn)
        csg = get_csg(conn, csg_id)
        if not csg:
            flash("CSG no encontrado.", "danger")
            return redirect(url_for("globalgap_portal.clientes_list"))
        cliente = get_etiqueta(conn, csg["etiqueta_id"])
        if request.method == "POST":
            ok, msg, _ = create_ambito(
                conn,
                etiqueta_id=csg["etiqueta_id"],
                csg_id=csg_id,
                nombre_huerto=request.form.get("nombre_huerto") or "",
                especie_cultivo=request.form.get("especie_cultivo") or "",
                plantilla_docs=request.form.get("plantilla_docs") or "cerezos",
                razon_social=request.form.get("razon_social") or "",
                direccion=request.form.get("direccion") or "",
            )
            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(
                    url_for("globalgap_portal.clientes_detalle", etiqueta_id=csg["etiqueta_id"])
                )
    finally:
        conn.close()

    return render_template(
        "globalgap_portal/clientes/form_ambito.html",
        active_key="ClientesGlobalGAP",
        page_title=f"Nuevo ámbito — {csg['codigo_csg']}",
        cliente=cliente,
        csg=csg,
        plantillas=_PLANTILLAS,
    )


@bp.route("/ambito/<int:ambito_id>")
@_require_globalgap_tenant
def entrar_ambito(ambito_id: int):
    conn = _conn()
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
