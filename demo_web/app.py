from __future__ import annotations

import time

import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from demo_web.auth.decorators import login_required
from demo_web.auth.routes import bp as auth_bp
from demo_web.blueprints.modules import bp as modules_bp
from demo_web.config import Config
from demo_web.pricing import clp as format_clp
from demo_web.services.erp_loader import bind_tenant_context
from demo_web.tenants import RUBRO_BRAND, RUBRO_SUBTITLE, RUBRO_TITLE, get_tenant, list_tenants


def _menu_con_planes(menu: list, tenant_slug: str | None) -> list:
    """Agrega Planes al menú solo en tenant DEMO Agrícola."""
    if (tenant_slug or "").strip().lower() != "demo":
        return menu
    items = list(menu or [])
    if any(it.get("endpoint") == "planes" for it in items):
        return items
    planes_item = {"label": "Planes", "key": "Planes", "endpoint": "planes"}
    insert_at = len(items)
    for i, it in enumerate(items):
        if it.get("key") in {"Soporte", "Manual", "Administracion"}:
            insert_at = i
            break
    items.insert(insert_at, planes_item)
    return items


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

    @app.template_filter("clp")
    def _clp_filter(n):
        return format_clp(n)

    @app.before_request
    def _bind_tenant():
        slug = session.get("tenant_slug")
        bind_tenant_context(slug if slug else None)


    @app.before_request
    def _agricola_session_idle():
        if not session.get("email"):
            return None
        endpoint = request.endpoint or ""
        if endpoint.startswith("static") or endpoint in {
            "auth.login",
            "auth.logout",
            "auth.master_entry",
            "auth.select_tenant",
            "logo_asset",
        }:
            return None
        now = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
        try:
            last = float(session.get("last_activity") or now)
        except (TypeError, ValueError):
            last = now
        if (now - last) > idle_limit:
            session.clear()
            if endpoint in {"session_status", "session_continue"} or (request.path or "").endswith(
                "/api/session-status"
            ) or (request.path or "").endswith("/api/session-continue"):
                return {"ok": False, "error": "session_expired"}, 401
            return redirect(url_for("auth.login"))
        if endpoint == "session_continue":
            session["last_activity"] = now
        elif endpoint not in {"session_status"}:
            session["last_activity"] = now
        return None

    @app.get("/api/session-status")
    def session_status():
        if not session.get("email"):
            return {"ok": False, "error": "session_expired"}, 401
        now = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
        warn = int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120)
        try:
            last = float(session.get("last_activity") or now)
        except (TypeError, ValueError):
            last = now
        idle_for = max(0.0, now - last)
        return {
            "ok": True,
            "idle_limit": idle_limit,
            "warn_seconds": warn,
            "idle_for": round(idle_for, 1),
            "idle_left": round(max(0.0, idle_limit - idle_for), 1),
        }

    @app.post("/api/session-continue")
    def session_continue():
        if not session.get("email"):
            return {"ok": False, "error": "session_expired"}, 401
        session["last_activity"] = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
        return {"ok": True, "idle_left": idle_limit}

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

    @app.route("/planes")
    @login_required
    def planes():
        """Valoración de módulos (DEMO Agrícola)."""
        from demo_web.pricing import (
            MODULOS_FEE,
            PACK,
            PACK_CAMPO,
            PACK_OFICINA,
            PACK_PATIO,
            suma_modulos,
            suma_modulos_keys,
        )

        slug = (session.get("tenant_slug") or "").strip().lower()
        if slug != "demo":
            flash("Esta vista aplica al tenant DEMO Agrícola.", "info")
            return redirect(url_for("modules.dashboard"))
        suma = suma_modulos()
        suma_campo = suma_modulos_keys(PACK_CAMPO["modulos"])
        suma_patio = suma_modulos_keys(PACK_PATIO["modulos"])
        suma_oficina = suma_modulos_keys(PACK_OFICINA["modulos"])
        pagos = [int(m["fee"]) for m in MODULOS_FEE.values() if int(m["fee"]) > 0]
        return render_template(
            "planes.html",
            active_key="Planes",
            modulos=MODULOS_FEE,
            pack=PACK,
            pack_campo=PACK_CAMPO,
            pack_patio=PACK_PATIO,
            pack_oficina=PACK_OFICINA,
            suma=suma,
            suma_campo=suma_campo,
            suma_patio=suma_patio,
            suma_oficina=suma_oficina,
            ahorro=max(0, suma - int(PACK["fee"])),
            ahorro_campo=max(0, suma_campo - int(PACK_CAMPO["fee"])),
            ahorro_patio=max(0, suma_patio - int(PACK_PATIO["fee"])),
            ahorro_oficina=max(0, suma_oficina - int(PACK_OFICINA["fee"])),
            modulos_pago_min=min(pagos) if pagos else 0,
            clp=format_clp,
        )

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
            menu = _menu_con_planes(build_menu(user["email"], user["rol"]), tenant["slug"])
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
            "session_idle_limit": int(app.config.get("SESSION_IDLE_SECONDS") or 1200),
            "session_idle_warn": int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120),
            "clp": format_clp,
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


    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")

    return app
