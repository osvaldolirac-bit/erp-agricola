from __future__ import annotations

import os
from functools import wraps

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from urllib.parse import quote

from erp_master import tenant_admin as tad
from erp_master.bridge import mint_entry_token
from erp_master.config import Config
from erp_master.db import (
    ROL_LABEL,
    authenticate,
    change_master_password,
    close_db,
    create_master_user,
    delete_master_user,
    init_db,
    list_bitacora,
    list_master_users,
    log_bitacora,
    set_master_user_activo,
)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("master_email"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def super_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("master_email"):
            return redirect(url_for("login", next=request.path))
        if session.get("master_rol") != "super_admin":
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    return wrapped


def _admin_tenant_map(app: Flask) -> dict:
    return {t["slug"]: t for t in app.config["ADMIN_TENANTS"]}


def _get_admin_tenant(app: Flask, slug: str) -> dict | None:
    return _admin_tenant_map(app).get(slug)


def _can_manage_tenant(slug: str) -> bool:
    rol = session.get("master_rol")
    if rol == "super_admin":
        return True
    if rol == "admin":
        return session.get("master_tenant") == slug
    return False


def _session_user() -> dict:
    rol = session.get("master_rol") or "admin"
    return {
        "email": session.get("master_email") or "",
        "nombre": session.get("master_nombre") or "",
        "rol": rol,
        "rol_label": ROL_LABEL.get(rol, rol),
        "tenant_slug": session.get("master_tenant") or "",
        "is_super": rol == "super_admin",
    }


def create_app(config_object: type = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(config_object)

    db_path = app.config["DATABASE"]
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    @app.context_processor
    def inject_console_user():
        if session.get("master_email"):
            return {"user": _session_user(), "brand": app.config["BRAND_NAME"]}
        return {"user": None, "brand": app.config["BRAND_NAME"]}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("master_email"):
            return redirect(url_for("home"))

        error = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            user = authenticate(email, password)
            if user:
                session.clear()
                session["master_email"] = user["email"]
                session["master_nombre"] = user.get("nombre") or ""
                session["master_rol"] = user.get("rol") or "admin"
                session["master_tenant"] = user.get("tenant_slug") or ""
                session.permanent = True
                nxt = request.args.get("next") or url_for("home")
                if not str(nxt).startswith("/"):
                    nxt = url_for("home")
                return redirect(nxt)
            error = "Usuario o clave incorrectos."

        return render_template(
            "login.html",
            brand=app.config["BRAND_NAME"],
            tagline="Super consola · facultades separadas",
            error=error,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        admin_map = _admin_tenant_map(app)
        tenants_view = []
        for t in app.config["TENANTS"]:
            item = dict(t)
            item["adminable"] = t["slug"] in admin_map
            item["can_manage"] = item["adminable"] and _can_manage_tenant(t["slug"])
            # Mantención aplica a todos los clientes listados (LC, DEMO, Río Maipo).
            item["can_mantenimiento"] = _session_user()["is_super"] or item["can_manage"]
            item["en_mantenimiento"] = tad.get_mantenimiento(t["slug"])
            tenants_view.append(item)
        return render_template("home.html", tenants=tenants_view)

    @app.route("/clientes/<slug>/mantenimiento", methods=["POST"])
    @login_required
    def toggle_mantenimiento(slug: str):
        user = _session_user()
        admin_map = _admin_tenant_map(app)
        known = {t["slug"] for t in app.config["TENANTS"]}
        if slug not in known:
            return redirect(url_for("home"))
        if not (user["is_super"] or (slug in admin_map and _can_manage_tenant(slug))):
            return redirect(url_for("home"))
        activo = request.form.get("activo") == "1"
        tad.set_mantenimiento(slug, activo)
        log_bitacora(
            slug,
            user.get("email") or "",
            "MANTENCION_ON" if activo else "MANTENCION_OFF",
            "Sitio en mantención" if activo else "Sitio reactivado",
        )
        return redirect(url_for("home"))

    @app.route("/clientes/<slug>/entrar")
    @login_required
    def entrar_erp(slug: str):
        """Abre el ERP autenticado y va directo al dashboard."""
        tenants = {t["slug"]: t for t in app.config["TENANTS"]}
        tenant = tenants.get(slug)
        if not tenant or not tenant.get("url_dashboard"):
            return redirect(url_for("home"))
        secret = (app.config.get("BRIDGE_SECRET") or "").strip()
        email = (_session_user().get("email") or "").strip()
        log_bitacora(slug, email, "ENTRAR_ERP", "Ingreso al dashboard desde Super Consola")
        if not secret or not email:
            # Sin puente: caer al dashboard (pedirá login del ERP).
            return redirect(tenant["url_dashboard"])
        token = mint_entry_token(secret=secret, slug=slug, email=email)
        base = (tenant.get("url") or "/").rstrip("/")
        return redirect(f"{base}/login/master?t={quote(token)}")

    @app.route("/admin")
    @app.route("/admin/<slug>")
    @login_required
    def admin_legacy(slug: str | None = None):
        """Compat: /admin → inicio; /admin/<slug> → Super Consola."""
        if slug and _can_manage_tenant(slug) and _get_admin_tenant(app, slug):
            return redirect(url_for("super_consola", slug=slug, sec=request.args.get("sec")))
        return redirect(url_for("home"))

    @app.route("/plataforma/usuarios", methods=["GET", "POST"])
    @super_admin_required
    def consola_usuarios():
        msg = None
        msg_type = "ok"
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "crear":
                ok, text = create_master_user(
                    request.form.get("email") or "",
                    request.form.get("password") or "",
                    request.form.get("nombre") or "",
                    request.form.get("rol") or "admin",
                    request.form.get("tenant_slug") or "",
                )
            elif action == "clave":
                try:
                    uid = int(request.form.get("user_id") or 0)
                except ValueError:
                    uid = 0
                ok, text = change_master_password(uid, request.form.get("password") or "")
            elif action == "activar":
                try:
                    uid = int(request.form.get("user_id") or 0)
                except ValueError:
                    uid = 0
                ok, text = set_master_user_activo(uid, True)
            elif action == "desactivar":
                try:
                    uid = int(request.form.get("user_id") or 0)
                except ValueError:
                    uid = 0
                ok, text = set_master_user_activo(uid, False)
            elif action == "eliminar":
                try:
                    uid = int(request.form.get("user_id") or 0)
                except ValueError:
                    uid = 0
                ok, text = delete_master_user(uid)
            else:
                ok, text = False, "Acción no reconocida."
            msg, msg_type = text, ("ok" if ok else "error")

        return render_template(
            "consola_usuarios.html",
            users=list_master_users(),
            admin_tenants=app.config["ADMIN_TENANTS"],
            msg=msg,
            msg_type=msg_type,
        )

    @app.route("/consola/<slug>", methods=["GET", "POST"])
    @login_required
    def super_consola(slug: str):
        tenant = _get_admin_tenant(app, slug)
        if not tenant or not _can_manage_tenant(slug):
            return redirect(url_for("home"))

        msg = None
        msg_type = "ok"
        sec = (request.args.get("sec") or request.form.get("sec") or "usuarios").strip()
        allowed_sec = {"usuarios", "modulos", "respaldo", "bitacora"}
        if tenant.get("kind") == "demo":
            allowed_sec.add("plataforma")
        if sec not in allowed_sec:
            sec = "usuarios"

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            pre_target = ""
            try:
                pre_uid = int(request.form.get("user_id") or 0)
            except ValueError:
                pre_uid = 0
            if pre_uid and action in {
                "cambiar_rol",
                "cambiar_clave",
                "eliminar_usuario",
                "flags_usuario",
                "modulos_guardar",
            }:
                pre_target = _user_email_by_id(tenant, pre_uid)
            ok, text = _handle_admin_action(
                tenant, action, session.get("master_email") or ""
            )
            msg, msg_type = text, ("ok" if ok else "error")
            if ok:
                _log_admin_action(
                    tenant,
                    session.get("master_email") or "",
                    action,
                    text,
                    target_email=pre_target,
                )
            if action.startswith("modulos"):
                sec = "modulos"
            elif action.startswith("respaldo"):
                sec = "respaldo"
            elif action.startswith("reseed") or action.startswith("bitacora_erp") or action == "plataforma":
                sec = "plataforma" if tenant.get("kind") == "demo" else (
                    request.form.get("sec") or "usuarios"
                )
            else:
                sec = request.form.get("sec") or "usuarios"
                if sec not in allowed_sec:
                    sec = "usuarios"

        users = tad.list_users(tenant["db"], tenant["kind"])
        respaldo = tad.get_respaldo_config(tenant["db"])
        menu = tad.menu_for(tenant["kind"])
        roles = tad.roles_for(tenant["kind"])
        bitacora_rows = list_bitacora(tenant["slug"]) if sec == "bitacora" else []
        plataforma = (
            tad.get_plataforma_demo(tenant["db"])
            if tenant.get("kind") == "demo" and sec == "plataforma"
            else None
        )
        bitacora_erp_activa = tad.get_bitacora_erp(tenant["slug"])
        try:
            bitacora_erp_n = 0
            if sec in {"plataforma", "usuarios", "bitacora"}:
                with tad.tenant_conn(tenant["db"]) as _c:
                    bitacora_erp_n = int(
                        _c.execute("SELECT COUNT(*) AS n FROM bitacora").fetchone()["n"] or 0
                    )
        except Exception:
            bitacora_erp_n = 0

        mod_user_id = request.args.get("uid") or request.form.get("uid") or ""
        mod_email, mod_keys, mod_all = "", [], True
        try:
            uid_int = int(mod_user_id) if mod_user_id else 0
        except ValueError:
            uid_int = 0
        if uid_int:
            mod_email, mod_keys, mod_all = tad.get_user_modules(tenant["db"], uid_int)

        operadores = [u for u in users if u.get("es_operador")]
        manage_tenants = [
            t for t in app.config["ADMIN_TENANTS"] if _can_manage_tenant(t["slug"])
        ]

        return render_template(
            "super_consola.html",
            tenant=tenant,
            admin_tenants=manage_tenants,
            sec=sec,
            users=users,
            operadores=operadores,
            roles=roles,
            menu=menu,
            respaldo=respaldo,
            frecuencias=tad.FRECUENCIAS,
            mod_user_id=uid_int or "",
            mod_email=mod_email,
            mod_keys=mod_keys,
            mod_all=mod_all,
            bitacora_rows=bitacora_rows,
            plataforma=plataforma,
            bitacora_erp_activa=bitacora_erp_activa,
            bitacora_erp_n=bitacora_erp_n,
            msg=msg,
            msg_type=msg_type,
        )

    @app.get("/health")
    def health():
        return {"ok": True, "app": "erp_master"}

    return app


def _user_email_by_id(tenant: dict, user_id: int) -> str:
    try:
        for u in tad.list_users(tenant["db"], tenant["kind"]):
            if int(u.get("id") or 0) == int(user_id):
                return str(u.get("email") or "")
    except Exception:
        pass
    return f"#{user_id}"


def _log_admin_action(
    tenant: dict,
    master_email: str,
    action: str,
    result_text: str,
    target_email: str = "",
) -> None:
    slug = tenant["slug"]
    detalle = (result_text or "").strip()
    try:
        uid = int(request.form.get("user_id") or 0)
    except ValueError:
        uid = 0
    target = (target_email or "").strip() or (
        _user_email_by_id(tenant, uid) if uid else ""
    )

    if action == "crear_usuario":
        email = (request.form.get("email") or "").strip()
        rol = (request.form.get("rol") or "").strip()
        detalle = f"{email} · rol {rol}" if email else detalle
        accion = "CREAR_USUARIO"
    elif action == "cambiar_rol":
        rol = (request.form.get("rol") or "").strip()
        detalle = f"{target or f'#{uid}'} → rol {rol}"
        accion = "CAMBIAR_ROL"
    elif action == "cambiar_clave":
        detalle = target or f"#{uid}"
        accion = "CAMBIAR_CLAVE"
    elif action == "eliminar_usuario":
        detalle = target or f"#{uid}"
        accion = "ELIMINAR_USUARIO"
    elif action == "flags_usuario":
        flags = []
        if request.form.get("mail_tesoreria") == "1":
            flags.append("mail_tesoreria")
        if request.form.get("mail_petroleo") == "1":
            flags.append("mail_petroleo")
        if request.form.get("mail_riego") == "1":
            flags.append("mail_riego")
        if request.form.get("solo_lectura") == "1":
            flags.append("solo_lectura")
        detalle = f"{target or f'#{uid}'} · {', '.join(flags) if flags else 'sin flags'}"
        accion = "FLAGS_USUARIO"
    elif action == "modulos_guardar":
        mods = request.form.getlist("modulos")
        if request.form.get("todos") == "1":
            detalle = f"{target or f'#{uid}'} · todos los módulos"
        else:
            detalle = f"{target or f'#{uid}'} · {len(mods)} módulos"
        accion = "MODULOS"
    elif action == "respaldo_guardar":
        email = (request.form.get("email") or "").strip()
        activo = "activo" if request.form.get("activo") == "1" else "inactivo"
        detalle = f"{email or '—'} · {activo}"
        accion = "RESPALDO"
    elif action == "reseed_demo":
        detalle = "Re-siembra datos ficticios DEMO"
        accion = "RESEED_DEMO"
    elif action == "bitacora_erp_toggle":
        detalle = "Bitácora ERP ON" if request.form.get("activo") == "1" else "Bitácora ERP OFF"
        accion = "BITACORA_ERP"
    elif action == "bitacora_erp_vaciar":
        detalle = "Bitácora ERP vaciada"
        accion = "BITACORA_ERP_CLEAR"
    else:
        accion = (action or "ACCION").upper()
    log_bitacora(slug, master_email, accion, detalle)


def _handle_admin_action(tenant: dict, action: str, master_email: str) -> tuple[bool, str]:
    db = tenant["db"]
    kind = tenant["kind"]

    if action == "crear_usuario":
        return tad.create_user(
            db,
            kind,
            request.form.get("email") or "",
            request.form.get("password") or "",
            request.form.get("rol") or "operador",
            dias_demo=int(request.form.get("dias_demo") or 30),
            invitado_por=master_email,
            enviar_invitacion=(
                kind != "demo" or request.form.get("enviar_invitacion") == "1"
            ),
        )

    if action == "reseed_demo":
        if kind != "demo":
            return False, "Re-seed solo aplica al DEMO."
        if request.form.get("confirm") != "1":
            return False, "Debe confirmar el re-seed."
        return tad.reseed_demo(db)

    if action == "bitacora_erp_toggle":
        activo = request.form.get("activo") == "1"
        return tad.set_bitacora_erp(tenant["slug"], activo)

    if action == "bitacora_erp_vaciar":
        if request.form.get("confirm") != "1":
            return False, "Debe confirmar vaciar la bitácora."
        ok, text = tad.clear_bitacora_erp(db)
        if ok:
            tad.set_bitacora_erp(tenant["slug"], False)
        return ok, text

    if action == "cambiar_rol":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        return tad.change_role(db, kind, uid, request.form.get("rol") or "")

    if action == "cambiar_clave":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        return tad.change_password(db, kind, uid, request.form.get("password") or "")

    if action == "eliminar_usuario":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        return tad.delete_user(db, kind, uid)

    if action == "flags_usuario":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        return tad.set_mail_flags(
            db,
            kind,
            uid,
            mail_tesoreria=request.form.get("mail_tesoreria") == "1",
            mail_petroleo=request.form.get("mail_petroleo") == "1",
            mail_riego=request.form.get("mail_riego") == "1",
            solo_lectura=request.form.get("solo_lectura") == "1",
        )

    if action == "modulos_guardar":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        selected = request.form.getlist("modulos")
        if request.form.get("todos") == "1":
            selected = [k for k, _ in tad.menu_for(kind)]
        return tad.save_user_modules(db, kind, uid, selected)

    if action == "respaldo_guardar":
        return tad.save_respaldo_config(
            db,
            request.form.get("email") or "",
            request.form.get("activo") == "1",
            request.form.get("freq_datos") or "diario",
            request.form.get("freq_codigo") or "semanal",
        )

    return False, "Acción no reconocida."
