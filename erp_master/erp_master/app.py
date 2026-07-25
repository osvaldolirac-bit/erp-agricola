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

from erp_master import tenant_admin as tad
from erp_master.config import Config
from erp_master.db import (
    ROL_LABEL,
    authenticate,
    change_master_password,
    close_db,
    create_master_user,
    delete_master_user,
    init_db,
    list_master_users,
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
        return redirect(url_for("home"))

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
        if sec not in {"usuarios", "modulos", "respaldo"}:
            sec = "usuarios"

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            ok, text = _handle_admin_action(
                tenant, action, session.get("master_email") or ""
            )
            msg, msg_type = text, ("ok" if ok else "error")
            if action.startswith("modulos"):
                sec = "modulos"
            elif action.startswith("respaldo"):
                sec = "respaldo"
            else:
                sec = "usuarios"

        users = tad.list_users(tenant["db"], tenant["kind"])
        respaldo = tad.get_respaldo_config(tenant["db"])
        menu = tad.menu_for(tenant["kind"])
        roles = tad.roles_for(tenant["kind"])

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
            msg=msg,
            msg_type=msg_type,
        )

    @app.route("/consola/usuarios", methods=["GET", "POST"])
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

    @app.get("/health")
    def health():
        return {"ok": True, "app": "erp_master"}

    return app


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
        )

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
