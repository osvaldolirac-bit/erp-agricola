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
from erp_master.db import authenticate, close_db, init_db


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("master_email"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _admin_tenant_map(app: Flask) -> dict:
    return {t["slug"]: t for t in app.config["ADMIN_TENANTS"]}


def _get_admin_tenant(app: Flask, slug: str) -> dict | None:
    return _admin_tenant_map(app).get(slug)


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
                session.permanent = True
                nxt = request.args.get("next") or url_for("home")
                if not str(nxt).startswith("/"):
                    nxt = url_for("home")
                return redirect(nxt)
            error = "Usuario o clave incorrectos."

        return render_template(
            "login.html",
            brand=app.config["BRAND_NAME"],
            tagline=app.config["BRAND_TAGLINE"],
            error=error,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        return render_template(
            "home.html",
            brand=app.config["BRAND_NAME"],
            tagline=app.config["BRAND_TAGLINE"],
            tenants=app.config["TENANTS"],
            admin_tenants=app.config["ADMIN_TENANTS"],
            email=session.get("master_email"),
            nombre=session.get("master_nombre") or "",
        )

    @app.route("/admin")
    @login_required
    def admin_index():
        return render_template(
            "admin/index.html",
            brand=app.config["BRAND_NAME"],
            admin_tenants=app.config["ADMIN_TENANTS"],
            email=session.get("master_email"),
            nombre=session.get("master_nombre") or "",
        )

    @app.route("/admin/<slug>", methods=["GET", "POST"])
    @login_required
    def admin_tenant(slug: str):
        tenant = _get_admin_tenant(app, slug)
        if not tenant:
            return redirect(url_for("admin_index"))

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

        return render_template(
            "admin/tenant.html",
            brand=app.config["BRAND_NAME"],
            tenant=tenant,
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
            email=session.get("master_email"),
            nombre=session.get("master_nombre") or "",
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
