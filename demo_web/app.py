from __future__ import annotations

import os

from flask import Flask, redirect, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from demo_web.auth.routes import bp as auth_bp
from demo_web.blueprints.modules import bp as modules_bp
from demo_web.config import Config
from demo_web.services.erp_loader import bind_tenant_context
from demo_web.tenants import RUBRO_BRAND, RUBRO_SUBTITLE, RUBRO_TITLE, get_tenant, list_tenants


def create_app(config_class=Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(config_class)

    # Cookie path acotado al rubro
    app.config["SESSION_COOKIE_PATH"] = (
        app.config.get("APPLICATION_ROOT") or "/agricola"
    ).rstrip("/") or "/"

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    app.register_blueprint(auth_bp)
    app.register_blueprint(modules_bp)

    from demo_web.blueprints.salida_petroleo import bp as salida_petroleo_bp

    app.register_blueprint(salida_petroleo_bp)

    from demo_web.services.mantenimiento import register_mantenimiento

    register_mantenimiento(app)

    @app.before_request
    def _bind_tenant():
        slug = session.get("tenant_slug")
        bind_tenant_context(slug if slug else None)

    @app.route("/")
    def root():
        if session.get("email") and session.get("tenant_slug"):
            return redirect(url_for("modules.dashboard"))
        return redirect(url_for("auth.login"))

    @app.route("/assets/logo")
    def logo_asset():
        from flask import abort, send_file

        from demo_web.services.branding import find_logo_path

        path = find_logo_path(prefer_master=True)
        if not path:
            abort(404)
        return send_file(path, max_age=3600)

    @app.context_processor
    def inject_globals():
        from demo_web.auth.decorators import build_menu
        from demo_web.services.branding import find_logo_path
        from flask import request, url_for

        user = None
        menu = []
        tenant = get_tenant(session.get("tenant_slug"))
        if session.get("email") and tenant:
            user = {
                "email": session["email"],
                "rol": session.get("rol", "operador"),
                "tenant_slug": tenant["slug"],
                "tenant_nombre": tenant["nombre"],
            }
            menu = build_menu(user["email"], user["rol"])
        prefix = (app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
        # Login/selector: marca del rubro. Dentro del ERP: nombre del tenant.
        if session.get("email") and tenant:
            title = tenant["nombre"]
            brand = tenant["nombre"]
            subtitle = tenant.get("descripcion") or ""
            badge = ""
            icon = ""
            logo_url = None  # sin logo de cliente en esquina; nav usa brand texto
            erp_app = tenant["erp_app"]
        else:
            title = app.config.get("ERP_TITLE", RUBRO_TITLE)
            brand = app.config.get("ERP_BRAND", RUBRO_BRAND)
            subtitle = app.config.get("ERP_LOGIN_SUBTITLE", RUBRO_SUBTITLE)
            badge = app.config.get("ERP_LOGIN_BADGE", "") or ""
            icon = app.config.get("ERP_LOGIN_ICON", "") or ""
            logo_url = url_for("logo_asset") if find_logo_path(prefer_master=True) else None
            erp_app = "agricola"
        return {
            "current_user": user,
            "nav_menu": menu,
            "url_prefix": prefix,
            "request": request,
            "erp_title": title,
            "erp_brand": brand,
            "erp_login_badge": badge,
            "erp_login_icon": icon,
            "erp_login_subtitle": subtitle,
            "erp_app": erp_app,
            "tenant": tenant,
            "logo_url": logo_url,
            "static_version": config_class.static_version(),
        }

    @app.after_request
    def static_no_cache(response):
        from flask import request

        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    with app.app_context():
        from demo_web.services.demo_loader import init_demo_db
        from demo_web.services.salida_petroleo import migrar_tabla

        init_demo_db()
        for t in list_tenants():
            bind_tenant_context(t["slug"])
            try:
                migrar_tabla()
            except Exception:
                pass
        bind_tenant_context(None)

    return app
