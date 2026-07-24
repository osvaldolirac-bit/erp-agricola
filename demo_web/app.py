from __future__ import annotations

import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from demo_web.auth.routes import bp as auth_bp
from demo_web.blueprints.modules import bp as modules_bp
from demo_web.config import Config


def create_app(config_class=Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(config_class)

    os.environ.setdefault("ERP_APP", app.config.get("ERP_APP", "demo"))
    os.environ.setdefault("ERP_DEMO_DB", app.config["DATABASE_PATH"])
    os.environ.setdefault("ERP_DB", app.config["DATABASE_PATH"])
    os.environ.setdefault("ERP_DEMO_SECRETS", app.config["SECRETS_PATH"])
    os.environ.setdefault("ERP_SECRETS", app.config["SECRETS_PATH"])

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    app.register_blueprint(auth_bp)
    app.register_blueprint(modules_bp)

    if app.config.get("ERP_APP") in ("concepcion", "demo"):
        from demo_web.blueprints.salida_petroleo import bp as salida_petroleo_bp

        app.register_blueprint(salida_petroleo_bp)

    @app.route("/")
    def root():
        from flask import redirect, session, url_for

        if session.get("email"):
            return redirect(url_for("modules.dashboard"))
        return redirect(url_for("auth.login"))

    @app.route("/assets/logo")
    def logo_asset():
        from flask import abort, send_file

        from demo_web.services.branding import find_logo_path

        path = find_logo_path()
        if not path:
            abort(404)
        return send_file(path, max_age=3600)

    @app.context_processor
    def inject_globals():
        from demo_web.auth.decorators import build_menu
        from demo_web.services.branding import find_logo_path
        from flask import request, session, url_for

        user = None
        menu = []
        if session.get("email"):
            user = {"email": session["email"], "rol": session.get("rol", "operador")}
            menu = build_menu(user["email"], user["rol"])
        prefix = app.config["APPLICATION_ROOT"].rstrip("/")
        logo_url = url_for("logo_asset") if find_logo_path() else None
        return {
            "current_user": user,
            "nav_menu": menu,
            "url_prefix": prefix,
            "request": request,
            "erp_title": app.config.get("ERP_TITLE", "ERP"),
            "erp_brand": app.config.get("ERP_BRAND", "ERP"),
            "erp_login_badge": app.config.get("ERP_LOGIN_BADGE", ""),
            "erp_login_icon": app.config.get("ERP_LOGIN_ICON", "🚜"),
            "erp_login_subtitle": app.config.get("ERP_LOGIN_SUBTITLE", ""),
            "erp_app": app.config.get("ERP_APP", "demo"),
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

        init_demo_db()
        if app.config.get("ERP_APP") in ("concepcion", "demo"):
            from demo_web.services.salida_petroleo import migrar_tabla

            try:
                migrar_tabla()
            except Exception:
                pass

    return app
