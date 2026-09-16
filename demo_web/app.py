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
from demo_web.pricing import pricing_context
from demo_web.services.erp_loader import bind_tenant_context
from demo_web.tenants import RUBRO_BRAND, RUBRO_SUBTITLE, RUBRO_TITLE, get_tenant, list_tenants

# Claves de menú que van bajo "Sistema" (no en el listado operativo).
_SISTEMA_KEYS = frozenset({"Soporte", "Manual", "Administracion"})


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

    from demo_web.blueprints.globalgap_portal import bp as globalgap_portal_bp

    app.register_blueprint(globalgap_portal_bp)

    from demo_web.blueprints.registro_riego import bp as registro_riego_bp
    from demo_web.blueprints.salida_petroleo import bp as salida_petroleo_bp

    app.register_blueprint(registro_riego_bp)
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
    def _globalgap_tenant_guard():
        if session.get("tenant_slug") != "globalgap" or not session.get("email"):
            return None
        endpoint = request.endpoint or ""
        allowed_prefixes = (
            "globalgap_portal.",
            "modules.globalgap",
            "modules.soporte",
            "modules.manual",
            "modules.pdf_download",
            "static",
        )
        if endpoint in {"session_status", "session_continue", "tenant_logo_asset", "logo_asset"}:
            return None
        if any(endpoint.startswith(p) for p in allowed_prefixes):
            return None
        if endpoint == "modules.dashboard":
            return redirect(url_for("globalgap_portal.panel"))
        if endpoint.startswith("modules."):
            return redirect(url_for("globalgap_portal.panel"))
        return None

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
            "auth.elegir_empresa",
            "globalgap_portal.login",
            "globalgap_portal.logout",
            "globalgap_portal.root",
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
            if session.get("tenant_slug") == "globalgap":
                return redirect(url_for("globalgap_portal.login"))
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
            from demo_web.auth.login_next import default_landing_url

            return redirect(default_landing_url())
        return redirect(url_for("auth.login"))

    @app.route("/assets/logo")
    def logo_asset():
        from flask import abort, send_file

        from demo_web.services.branding import find_logo_path

        path = find_logo_path(prefer_master=True)
        if not path:
            abort(404)
        return send_file(path, max_age=3600)

    @app.route("/assets/logo/tenant")
    def tenant_logo_asset():
        from flask import abort, send_file

        from demo_web.services.branding import find_tenant_logo_path

        slug = session.get("tenant_slug") or (request.args.get("tenant") or "").strip().lower()
        if not slug or not get_tenant(slug):
            abort(404)
        path = find_tenant_logo_path(slug)
        if not path:
            abort(404)
        return send_file(path, max_age=3600)

    @app.route("/assets/logo/master")
    def master_logo_asset():
        from flask import abort, send_file

        from demo_web.services.branding import find_master_logo_path

        path = find_master_logo_path()
        if not path:
            abort(404)
        return send_file(path, max_age=3600)


    @app.route("/probar", methods=["GET", "POST"])
    def probar():
        """Landing pública (IG): datos → código por mail → acceso demo (30 días)."""
        from datetime import datetime, timezone
        from urllib.parse import quote

        from demo_web.demo_probar import (
            CLAVE_DEMO,
            DEMO_DIAS_PRUEBA,
            append_lead,
            crear_usuario_demo,
            crear_y_enviar_codigo_probar,
            enviar_correo_acceso,
            es_permanente,
            validar_codigo_probar,
        )
        from demo_web.tenants import get_tenant

        if session.get("email") and session.get("tenant_slug"):
            flash("Ya tienes una sesión activa.", "ok")
            from demo_web.auth.login_next import default_landing_url

            return redirect(default_landing_url())

        dias = DEMO_DIAS_PRUEBA
        clave_demo = CLAVE_DEMO
        ok = False
        error = None
        info = None
        usuario_demo = ""
        login_url = url_for("auth.login")
        fecha_expira_txt = ""
        paso = "datos"
        pending_email = ""
        pending_nombre = ""
        pending_telefono = ""
        resend_wait = 0

        ten = get_tenant("demo") or {}
        secrets_path = ten.get("secrets") or os.environ.get(
            "ERP_DEMO_SECRETS", "/root/demo/.streamlit/secrets.toml"
        )
        db_path = ten.get("db") or os.environ.get("ERP_DEMO_DB", "/root/demo/erp_demo.db")

        if request.method == "POST":
            action = (request.form.get("action") or "enviar_codigo").strip()
            nombre = (request.form.get("nombre") or "").strip()
            telefono = (request.form.get("telefono") or "").strip()
            email = (request.form.get("email") or "").strip().lower()

            if action in ("enviar_codigo", "reenviar"):
                if not nombre or not telefono or not email or "@" not in email:
                    error = "Completa nombre, teléfono y un correo válido."
                elif es_permanente(email):
                    error = "Ese correo es interno. Usa otro mail para la prueba."
                elif not db_path:
                    error = "Demo no disponible. Intenta más tarde."
                else:
                    sent_ok, msg, meta = crear_y_enviar_codigo_probar(
                        secrets_path=secrets_path,
                        email=email,
                        nombre=nombre,
                        telefono=telefono,
                        force_resend=(action == "reenviar"),
                    )
                    if sent_ok:
                        paso = "codigo"
                        info = msg
                        pending_email = (meta or {}).get("email") or email
                        pending_nombre = (meta or {}).get("nombre") or nombre
                        pending_telefono = (meta or {}).get("telefono") or telefono
                        resend_wait = int((meta or {}).get("resend_wait") or 0)
                    else:
                        if meta:
                            paso = "codigo"
                            pending_email = meta.get("email") or email
                            pending_nombre = meta.get("nombre") or nombre
                            pending_telefono = meta.get("telefono") or telefono
                            resend_wait = int(meta.get("resend_wait") or 0)
                        error = msg

            elif action == "validar":
                codigo = (request.form.get("codigo") or "").strip()
                pending_email = email
                pending_nombre = nombre
                pending_telefono = telefono
                if not email or "@" not in email:
                    error = "Correo inválido. Vuelve a solicitar el código."
                    paso = "datos"
                else:
                    v_ok, v_msg, payload = validar_codigo_probar(email, codigo)
                    if not v_ok:
                        error = v_msg
                        paso = "codigo"
                        if payload:
                            pending_nombre = payload.get("nombre") or nombre
                            pending_telefono = payload.get("telefono") or telefono
                    else:
                        nombre_u = (payload or {}).get("nombre") or nombre
                        telefono_u = (payload or {}).get("telefono") or telefono
                        email_u = (payload or {}).get("email") or email
                        c_ok, c_msg, exp = crear_usuario_demo(
                            db_path=db_path,
                            email=email_u,
                            nombre=nombre_u,
                            telefono=telefono_u,
                            dias=dias,
                            clave=clave_demo,
                        )
                        if not c_ok:
                            error = c_msg or "No se pudo crear el acceso. Intenta de nuevo."
                            paso = "datos"
                        else:
                            try:
                                append_lead(
                                    {
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "producto": "agricola",
                                        "nombre": nombre_u,
                                        "telefono": telefono_u,
                                        "email": email_u,
                                        "fecha_expira": exp,
                                        "ip": (
                                            request.headers.get("X-Forwarded-For")
                                            or request.remote_addr
                                            or ""
                                        )[:80],
                                        "verificado_mail": True,
                                    }
                                )
                            except Exception:
                                pass
                            try:
                                from demo_web.master_bitacora import log_master_bitacora

                                log_master_bitacora(
                                    "demo",
                                    email_u,
                                    "PRUEBA_INICIO",
                                    f"{nombre_u} · {telefono_u} · vence {exp}",
                                )
                            except Exception:
                                pass
                            ok = True
                            usuario_demo = email_u
                            login_url = f"{url_for('auth.login')}?acceso={quote(email_u)}"
                            try:
                                from datetime import date as _date

                                f = _date.fromisoformat(exp[:10])
                                fecha_expira_txt = f.strftime("%d-%m-%Y")
                            except Exception:
                                fecha_expira_txt = exp
                            try:
                                enviar_correo_acceso(
                                    secrets_path=secrets_path,
                                    email=email_u,
                                    password_plain=clave_demo,
                                    fecha_expira=exp,
                                    dias=dias,
                                    login_url=f"https://erpmaster.cl/agricola/login?acceso={quote(email_u)}",
                                )
                            except Exception:
                                pass
            else:
                error = "Acción no válida."

        return render_template(
            "probar.html",
            dias_prueba=dias,
            ok=ok,
            error=error,
            info=info,
            usuario_demo=usuario_demo,
            clave_demo=clave_demo,
            login_url=login_url,
            fecha_expira_txt=fecha_expira_txt,
            paso=paso,
            pending_email=pending_email,
            pending_nombre=pending_nombre,
            pending_telefono=pending_telefono,
            resend_wait=resend_wait,
        )


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
            labels_for_keys,
            suma_modulos,
            suma_modulos_keys,
            validar_conexion_packs,
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
            body_class="planes-page",
            modulos=MODULOS_FEE,
            pack=PACK,
            pack_campo=PACK_CAMPO,
            pack_patio=PACK_PATIO,
            pack_oficina=PACK_OFICINA,
            pack_campo_labels=labels_for_keys(PACK_CAMPO.get("nucleo") or ()),
            pack_patio_labels=labels_for_keys(PACK_PATIO.get("nucleo") or ()),
            pack_oficina_labels=labels_for_keys(PACK_OFICINA.get("nucleo") or ()),
            suma=suma,
            suma_campo=suma_campo,
            suma_patio=suma_patio,
            suma_oficina=suma_oficina,
            ahorro=max(0, suma - int(PACK["fee"])),
            ahorro_campo=max(0, suma_campo - int(PACK_CAMPO["fee"])),
            ahorro_patio=max(0, suma_patio - int(PACK_PATIO["fee"])),
            ahorro_oficina=max(0, suma_oficina - int(PACK_OFICINA["fee"])),
            modulos_pago_min=min(pagos) if pagos else 0,
            pack_issues=validar_conexion_packs(),
            clp=format_clp,
        )

    @app.context_processor
    def inject_globals():
        from demo_web.auth.decorators import build_menu
        from demo_web.services.branding import (
            find_logo_path,
            find_master_logo_path,
            find_tenant_logo_path,
        )
        from flask import request, url_for

        user = None
        menu = []
        nav_ops: list = []
        nav_sistema: list = []
        home_url = url_for("auth.login")
        tenant = get_tenant(session.get("tenant_slug"))
        if session.get("email") and tenant:
            from demo_web.auth.login_next import default_landing_url

            home_url = default_landing_url()
            user = {
                "email": session["email"],
                "rol": session.get("rol", "operador"),
                "tenant_slug": tenant["slug"],
                "tenant_nombre": tenant["nombre"],
            }
            menu = build_menu(user["email"], user["rol"])
            for it in menu:
                if it.get("key") in _SISTEMA_KEYS:
                    nav_sistema.append(it)
                else:
                    nav_ops.append(it)
        prefix = (app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
        master_logo_url = None
        # Login/selector: marca del rubro. Dentro del ERP: nombre del tenant.
        if session.get("email") and tenant:
            title = tenant["nombre"]
            brand = tenant["nombre"]
            subtitle = tenant.get("descripcion") or ""
            badge = ""
            icon = ""
            erp_app = tenant["erp_app"]
            if find_tenant_logo_path(tenant["slug"]):
                logo_url = url_for("tenant_logo_asset")
            else:
                logo_url = None
            if tenant["slug"] == "concepcion" and find_master_logo_path():
                master_logo_url = url_for("master_logo_asset")
        else:
            title = app.config.get("ERP_TITLE", RUBRO_TITLE)
            brand = app.config.get("ERP_BRAND", RUBRO_BRAND)
            subtitle = app.config.get("ERP_LOGIN_SUBTITLE", RUBRO_SUBTITLE)
            badge = app.config.get("ERP_LOGIN_BADGE", "") or ""
            icon = app.config.get("ERP_LOGIN_ICON", "") or ""
            logo_url = url_for("logo_asset") if find_logo_path(prefer_master=True) else None
            erp_app = "agricola"
        pricing = pricing_context(tenant["slug"] if tenant else None)
        return {
            "current_user": user,
            "nav_menu": menu,
            "nav_ops": nav_ops,
            "nav_sistema": nav_sistema,
            "home_url": home_url,
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
            "master_logo_url": master_logo_url,
            "static_version": config_class.static_version(),
            "session_idle_limit": int(app.config.get("SESSION_IDLE_SECONDS") or 1200),
            "session_idle_warn": int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120),
            "clp": format_clp,
            "solo_lectura": bool(session.get("solo_lectura")) or (session.get("rol") == "lector"),
            **pricing,
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
        from demo_web.services.registro_riego import migrar_tabla as migrar_riego
        from demo_web.services.salida_petroleo import migrar_tabla as migrar_petroleo

        init_demo_db()
        for t in list_tenants():
            bind_tenant_context(t["slug"])
            try:
                migrar_petroleo()
                migrar_riego()
            except Exception:
                pass
        bind_tenant_context(None)


    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")

    return app
