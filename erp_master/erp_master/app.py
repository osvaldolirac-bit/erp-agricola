from __future__ import annotations

import os
import time
from functools import wraps

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    send_file,
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



def _read_meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                parts = v.strip().split()
                if not parts:
                    continue
                try:
                    out[k] = int(parts[0])  # kB
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def host_resource_stats() -> dict:
    """Indicadores live de RAM / swap / disco del VPS (valores en bytes)."""
    mi = _read_meminfo()
    mem_total = mi.get("MemTotal", 0) * 1024
    mem_avail = mi.get("MemAvailable", 0) * 1024
    mem_used = max(mem_total - mem_avail, 0)
    swap_total = mi.get("SwapTotal", 0) * 1024
    swap_free = mi.get("SwapFree", 0) * 1024
    swap_used = max(swap_total - swap_free, 0)
    try:
        st = os.statvfs("/")
        disk_total = st.f_frsize * st.f_blocks
        disk_free = st.f_frsize * st.f_bavail
        disk_used = max(disk_total - disk_free, 0)
    except OSError:
        disk_total = disk_free = disk_used = 0

    def _pct(used: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(100.0 * used / total, 1)

    def _level(pct: float) -> str:
        if pct >= 90:
            return "crit"
        if pct >= 75:
            return "warn"
        return "ok"

    mem_pct = _pct(mem_used, mem_total)
    swap_pct = _pct(swap_used, swap_total) if swap_total else 0.0
    disk_pct = _pct(disk_used, disk_total)
    return {
        "mem_total": mem_total,
        "mem_used": mem_used,
        "mem_avail": mem_avail,
        "mem_pct": mem_pct,
        "mem_level": _level(mem_pct),
        "swap_total": swap_total,
        "swap_used": swap_used,
        "swap_pct": swap_pct,
        "swap_level": _level(swap_pct) if swap_total else "ok",
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_pct": disk_pct,
        "disk_level": _level(disk_pct),
        "loadavg": os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0),
    }


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



def _safe_next_url(nxt: str | None) -> str:
    """Evita open-redirect y antepone SCRIPT_NAME (/consola) a paths de la app."""
    from flask import request, url_for

    home = url_for("home")
    raw = (nxt or "").strip()
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return home
    script = (request.script_root or "").rstrip("/")
    if script:
        if raw == script or raw.startswith(script + "/"):
            return raw
        return script + raw
    return raw

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
        brand = app.config["BRAND_NAME"]
        if not session.get("master_email"):
            return {"user": None, "brand": brand, "soporte_badge": 0, "session_idle_limit": int(app.config.get("SESSION_IDLE_SECONDS") or 1200), "session_idle_warn": int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120)}
        user = _session_user()
        badge = 0
        try:
            manage = [
                t for t in app.config["ADMIN_TENANTS"] if _can_manage_tenant(t["slug"])
            ]
            badge = int(tad.list_tickets_soporte(manage).get("n_pendientes") or 0)
        except Exception:
            badge = 0
        return {"user": user, "brand": brand, "soporte_badge": badge, "session_idle_limit": int(app.config.get("SESSION_IDLE_SECONDS") or 1200), "session_idle_warn": int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120)}

    @app.before_request
    def _enforce_session_idle():
        """Cierra sesión tras inactividad real.

        El widget /api/host-stats hace polling y NO debe renovar la actividad;
        si no, la consola nunca expiraría con la pestaña abierta.
        """
        if not session.get("master_email"):
            return None
        endpoint = request.endpoint or ""
        if endpoint in {"login", "logout", "static"}:
            return None
        now = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 7200)
        last = session.get("last_activity")
        try:
            last_f = float(last) if last is not None else None
        except (TypeError, ValueError):
            last_f = None
        if last_f is not None and (now - last_f) > idle_limit:
            session.clear()
            if endpoint == "host_stats_api" or (request.path or "").startswith("/api/"):
                return {"ok": False, "error": "session_expired"}, 401
            nxt = request.path if (request.path or "").startswith("/") else None
            return redirect(url_for("login", next=nxt))
        # Renovar actividad solo con uso real (no polling pasivo)
        if endpoint not in {"host_stats_api", "health", "session_status"}:
            session["last_activity"] = now
        elif last_f is None:
            session["last_activity"] = now
        return None

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
                session["last_activity"] = time.time()
                session.permanent = True
                nxt = _safe_next_url(request.args.get("next"))
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
            # Mantención aplica a todos los clientes listados.
            item["can_mantenimiento"] = _session_user()["is_super"] or item["can_manage"]
            item["en_mantenimiento"] = tad.get_mantenimiento(t["slug"])
            kind = (admin_map.get(t["slug"]) or {}).get("kind") or ""
            producto = (t.get("producto") or "").strip().lower()
            if not producto:
                producto = "comercial" if kind == "comercial" else "agricola"
            item["producto"] = producto
            item["kind"] = kind or ("comercial" if producto == "comercial" else "agricola")
            item["producto_label"] = "Comercial" if producto == "comercial" else "ERP Agrícola"
            item["abrir_label"] = "Abrir Comercial" if producto == "comercial" else "Abrir ERP"
            tenants_view.append(item)
        groups = [
            {
                "key": "agricola",
                "titulo": "ERP Agrícola",
                "subtitulo": "Operación de campo, compras, tesorería y módulos del ERP.",
                "tenants": [x for x in tenants_view if x.get("producto") == "agricola"],
            },
            {
                "key": "comercial",
                "titulo": "Comercial",
                "subtitulo": "Cotizaciones, clientes y cobranza. Independiente del ERP agrícola.",
                "tenants": [x for x in tenants_view if x.get("producto") == "comercial"],
            },
        ]
        return render_template(
            "home.html",
            tenants=tenants_view,
            product_groups=groups,
            host_stats=host_resource_stats(),
        )



    @app.get("/api/session-status")
    @login_required
    def session_status():
        """Estado de inactividad (no renueva actividad)."""
        now = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
        warn = int(app.config.get("SESSION_IDLE_WARN_SECONDS") or 120)
        try:
            last = float(session.get("last_activity") or now)
        except (TypeError, ValueError):
            last = now
        idle_for = max(0.0, now - last)
        idle_left = max(0.0, idle_limit - idle_for)
        return {
            "ok": True,
            "idle_limit": idle_limit,
            "warn_seconds": warn,
            "idle_for": round(idle_for, 1),
            "idle_left": round(idle_left, 1),
        }

    @app.post("/api/session-continue")
    @login_required
    def session_continue():
        """Extiende la sesión (botón Continuar / actividad)."""
        session["last_activity"] = time.time()
        idle_limit = int(app.config.get("SESSION_IDLE_SECONDS") or 1200)
        return {"ok": True, "idle_left": idle_limit}

    @app.get("/api/host-stats")
    @login_required
    def host_stats_api():
        """JSON live: RAM / swap / disco del VPS (solo sesión Master)."""
        return host_resource_stats()

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

    @app.route("/plataforma/soporte", methods=["GET", "POST"])
    @login_required
    def consola_soporte():
        """Inbox de tickets de todos los tenants administrables."""
        manage_tenants = [
            t for t in app.config["ADMIN_TENANTS"] if _can_manage_tenant(t["slug"])
        ]
        tenants_by_slug = {t["slug"]: t for t in manage_tenants}
        msg = None
        msg_type = "ok"
        filtro = (request.args.get("tenant") or request.form.get("tenant") or "").strip()
        vista = (request.args.get("vista") or request.form.get("vista") or "pendientes").strip()
        if vista not in {"pendientes", "historial", "todos"}:
            vista = "pendientes"

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            slug = (request.form.get("tenant_slug") or "").strip()
            tenant = tenants_by_slug.get(slug)
            if not tenant:
                msg, msg_type = "Cliente no autorizado.", "error"
            elif action == "responder":
                try:
                    tid = int(request.form.get("ticket_id") or 0)
                except ValueError:
                    tid = 0
                ok, text = tad.responder_ticket_soporte(
                    tenant,
                    tid,
                    request.form.get("respuesta") or "",
                    request.form.get("status") or "Abierto",
                )
                msg, msg_type = text, ("ok" if ok else "error")
                if ok:
                    log_bitacora(
                        slug,
                        session.get("master_email") or "",
                        "SOPORTE_RESPUESTA",
                        text,
                    )
                filtro = slug or filtro
                vista = "pendientes"
            elif action == "marcar_leido":
                try:
                    tid = int(request.form.get("ticket_id") or 0)
                except ValueError:
                    tid = 0
                tad.marcar_ticket_soporte_leido(tenant, tid)
                msg, msg_type = "Ticket marcado como leído.", "ok"
                filtro = slug or filtro

        data = tad.list_tickets_soporte(manage_tenants)
        if filtro and filtro in tenants_by_slug:
            data["pendientes"] = [
                t for t in data["pendientes"] if t.get("tenant_slug") == filtro
            ]
            data["historial"] = [
                t for t in data["historial"] if t.get("tenant_slug") == filtro
            ]
            data["n_pendientes"] = len(data["pendientes"])

        # Marcar como leídos los pendientes visibles (equivalente al inbox ERP).
        for item in data["pendientes"]:
            if item.get("nuevo"):
                ten = tenants_by_slug.get(item["tenant_slug"])
                if ten:
                    try:
                        tad.marcar_ticket_soporte_leido(ten, int(item["id"]))
                        item["nuevo"] = False
                    except Exception:
                        pass

        return render_template(
            "soporte.html",
            tenants=manage_tenants,
            filtro=filtro,
            vista=vista,
            tickets=data,
            msg=msg,
            msg_type=msg_type,
        )


    @app.route("/plataforma/comercial", methods=["GET", "POST"])
    @login_required
    def consola_comercial_suscripciones():
        """Tenants Comercial en prueba / en alta (+ pipeline usuarios DEMO)."""
        from erp_master import comercial_suscripciones as csus

        user = _session_user()
        manage = [t for t in app.config["ADMIN_TENANTS"] if _can_manage_tenant(t["slug"])]
        admin_com = [
            t
            for t in manage
            if t.get("producto") == "comercial" or t.get("kind") == "comercial"
        ]
        if user.get("is_super"):
            admin_com = [
                t
                for t in app.config["ADMIN_TENANTS"]
                if t.get("producto") == "comercial" or t.get("kind") == "comercial"
            ]
        if not admin_com:
            return redirect(url_for("home"))

        msg = None
        msg_type = "ok"

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            slug = (request.form.get("slug") or "").strip()
            if action == "set_estado":
                ok, text = csus.set_estado(
                    slug, request.form.get("estado") or "", admin_tenants=admin_com
                )
                msg, msg_type = text, ("ok" if ok else "error")
            elif action == "update_suscripcion":
                ok, text = csus.update_suscripcion(
                    slug,
                    plan=request.form.get("plan"),
                    fecha_vencimiento=request.form.get("fecha_vencimiento"),
                    notas=request.form.get("notas"),
                    mp_init_point=request.form.get("mp_init_point"),
                    mp_estado=request.form.get("mp_estado"),
                    admin_tenants=admin_com,
                )
                msg, msg_type = text, ("ok" if ok else "error")
            elif action == "update_planes_mp":
                ok, text = csus.update_planes_mp(
                    {
                        "modulos": request.form.get("mp_url_modulos") or "",
                        "ventas": request.form.get("mp_url_ventas") or "",
                        "compras": request.form.get("mp_url_compras") or "",
                        "comercial": request.form.get("mp_url_comercial") or "",
                    },
                    sociedad=request.form.get("sociedad_facturacion"),
                )
                msg, msg_type = text, ("ok" if ok else "error")
            else:
                msg, msg_type = "Acción no reconocida.", "error"

        grouped = csus.list_grouped(admin_com)
        return render_template(
            "comercial_suscripciones.html",
            grouped=grouped,
            msg=msg,
            msg_type=msg_type,
        )

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

    @app.route("/cliente/<slug>", methods=["GET", "POST"])
    @login_required
    def super_consola(slug: str):
        tenant = _get_admin_tenant(app, slug)
        if not tenant or not _can_manage_tenant(slug):
            return redirect(url_for("home"))

        msg = None
        msg_type = "ok"
        sec = (request.args.get("sec") or request.form.get("sec") or "usuarios").strip()
        allowed_sec = {"usuarios", "modulos", "respaldo", "alertas", "prorrateo", "bitacora"}
        if tenant.get("kind") == "demo":
            allowed_sec.add("plataforma")
        if tenant.get("kind") == "comercial":
            allowed_sec = {"usuarios", "alertas", "respaldo", "bitacora"}
            if tenant.get("slug") == "comercial-demo":
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
                "reenviar_invitacion",
                "extender_prueba",
            }:
                pre_target = _user_email_by_id(tenant, pre_uid)

            if action == "respaldo_download_db":
                ok, text, path = tad.crear_descarga_db(tenant["db"])
                if ok and path:
                    _log_admin_action(
                        tenant,
                        session.get("master_email") or "",
                        action,
                        "Descarga DB",
                        target_email="",
                    )
                    return send_file(
                        path,
                        as_attachment=True,
                        download_name=os.path.basename(path),
                    )
                msg, msg_type = text, "error"
            else:
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
            elif action.startswith("alertas"):
                sec = "alertas"
            elif action.startswith("prorrateo"):
                sec = "prorrateo"
            elif action.startswith("reseed") or action.startswith("bitacora_erp") or action == "plataforma":
                if tenant.get("kind") == "demo" or tenant.get("slug") == "comercial-demo":
                    sec = "plataforma"
                else:
                    sec = request.form.get("sec") or "usuarios"
            else:
                sec = request.form.get("sec") or "usuarios"
                if sec not in allowed_sec:
                    sec = "usuarios"

        users = tad.list_users(tenant["db"], tenant["kind"])
        estado_f = (request.args.get("estado") or "").strip().lower()
        users_view = users
        if estado_f == "contratar":
            users_view = [u for u in users if (u.get("plan_interes") or "").strip()]
        elif estado_f in {"prueba", "vencido", "alta"}:
            users_view = [u for u in users if (u.get("status") or "") == estado_f]
        respaldo = tad.get_respaldo_config(tenant["db"], producto=tenant.get("producto") or "")
        respaldo_edita_codigo = tad.es_owner_codigo_rubro(
            tenant.get("slug") or "", tenant.get("producto") or ""
        )
        respaldo_codigo_owner_label = tad.label_owner_codigo_rubro(
            tenant.get("producto") or ""
        )
        alertas = tad.get_mail_alertas(tenant.get("secrets") or "")
        prorrateo = (
            tad.get_prorrateo_cc(tenant["db"], tenant["kind"])
            if sec == "prorrateo"
            else None
        )
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
            if sec in {"plataforma", "usuarios", "bitacora", "alertas"}:
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

        def _producto_meta(ten: dict) -> dict:
            out = dict(ten)
            kind = out.get("kind") or ""
            producto = (
                out.get("producto")
                or ("comercial" if kind == "comercial" else "agricola")
            )
            producto = str(producto).strip().lower()
            out["producto"] = producto
            if producto == "constructora":
                out["producto_label"] = "Constructora"
                out["abrir_label"] = "Abrir Constructora"
            elif producto == "comercial":
                out["producto_label"] = "Comercial"
                out["abrir_label"] = "Abrir Comercial"
            else:
                out["producto_label"] = "ERP Agrícola"
                out["abrir_label"] = "Abrir ERP"
            return out

        tenant = _producto_meta(tenant)
        manage_tenants = [_producto_meta(x) for x in manage_tenants]

        return render_template(
            "super_consola.html",
            tenant=tenant,
            admin_tenants=manage_tenants,
            sec=sec,
            users=users,
            users_view=users_view,
            operadores=operadores,
            roles=roles,
            menu=menu,
            respaldo=respaldo,
            respaldo_edita_codigo=respaldo_edita_codigo,
            respaldo_codigo_owner_label=respaldo_codigo_owner_label,
            alertas=alertas,
            prorrateo=prorrateo,
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


    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")


    @app.route("/<slug>", methods=["GET", "POST"])
    def legacy_cliente_short(slug: str):
        """Compat: erpmaster.cl/consola/<slug> (bookmark antiguo) → /cliente/<slug>."""
        reserved = {
            "login", "logout", "admin", "static", "api", "plataforma",
            "clientes", "cliente", "favicon.ico", "health",
        }
        if slug in reserved:
            from flask import abort
            abort(404)
        admin_map = _admin_tenant_map(app)
        known = {t["slug"] for t in app.config.get("TENANTS") or []}
        known |= set(admin_map.keys())
        if slug not in known:
            from flask import abort
            abort(404)
        return redirect(url_for("super_consola", slug=slug, **request.args.to_dict()))

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
    elif action == "respaldo_enviar_datos":
        detalle = "Envío manual datos"
        accion = "RESPALDO_DATOS"
    elif action == "respaldo_enviar_codigo":
        detalle = "Envío manual código"
        accion = "RESPALDO_CODIGO"
    elif action == "respaldo_download_db":
        detalle = "Descarga DB"
        accion = "RESPALDO_DOWNLOAD"
    elif action == "alertas_guardar":
        detalle = (request.form.get("correo_receptor") or "").strip()
        accion = "MAIL_ALERTAS"
    elif action == "prorrateo_guardar":
        detalle = "Prorrateo CC actualizado"
        accion = "PRORRATEO_CC"
    elif action == "reenviar_invitacion":
        detalle = target or f"#{uid}"
        accion = "INVITACION"
    elif action == "extender_prueba":
        dias = (request.form.get("dias_demo") or "30").strip()
        detalle = f"{target or f'#{uid}'} · +{dias}d"
        accion = "EXTENDER_PRUEBA"
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
    if kind == "comercial":
        if action == "crear_usuario":
            es_demo = bool(tenant.get("es_demo")) or tenant.get("slug") == "comercial-demo"
            try:
                dias_demo = int(request.form.get("dias_demo") or 30)
            except (TypeError, ValueError):
                dias_demo = 30
            return tad.create_user_comercial(
                db,
                request.form.get("email") or "",
                request.form.get("password") or "",
                request.form.get("rol") or "Operador",
                request.form.get("nombre") or "",
                es_demo=es_demo,
                dias_demo=dias_demo,
                invitado_por=master_email,
                enviar_invitacion=request.form.get("enviar_invitacion") == "1",
                secrets_path=tenant.get("secrets") or "",
            )
        if action == "cambiar_rol":
            try:
                uid = int(request.form.get("user_id") or 0)
            except ValueError:
                uid = 0
            return tad.change_role_comercial(db, uid, request.form.get("rol") or "")
        if action == "cambiar_clave":
            try:
                uid = int(request.form.get("user_id") or 0)
            except ValueError:
                uid = 0
            return tad.change_password_comercial(db, uid, request.form.get("password") or "")
        if action == "eliminar_usuario":
            try:
                uid = int(request.form.get("user_id") or 0)
            except ValueError:
                uid = 0
            return tad.delete_user_comercial(db, uid)
        if action == "bitacora_erp_toggle":
            activo = request.form.get("activo") == "1"
            return tad.set_bitacora_erp(tenant["slug"], activo)
        if action == "bitacora_erp_vaciar":
            return False, "Comercial no usa bitácora ERP agrícola."
        if action == "reseed_demo":
            if tenant.get("slug") != "comercial-demo":
                return False, "Re-seed solo aplica al DEMO Comercial."
            if request.form.get("confirm") != "1":
                return False, "Debe confirmar el re-seed."
            return tad.reseed_comercial_demo(db)
        if action == "reenviar_invitacion":
            if not (tenant.get("es_demo") or tenant.get("slug") == "comercial-demo"):
                return False, "Reenviar invitación solo aplica al DEMO Comercial."
            try:
                uid = int(request.form.get("user_id") or 0)
            except ValueError:
                uid = 0
            try:
                dias_demo = int(request.form.get("dias_demo") or 30)
            except (TypeError, ValueError):
                dias_demo = 30
            return tad.reenviar_invitacion_comercial(
                db,
                uid,
                request.form.get("password") or "",
                master_email,
                secrets_path=tenant.get("secrets") or "",
                dias_demo=dias_demo,
            )
        if action not in {
            "alertas_guardar",
            "respaldo_guardar",
            "respaldo_enviar_datos",
            "respaldo_enviar_codigo",
            "respaldo_download_db",
        }:
            return False, "Esa acción es solo de ERP Agrícola. En Comercial use Alertas para el mail receptor, y aquí solo alta/rol/clave/eliminar usuarios."


    if action == "crear_usuario":
        return tad.create_user(
            db,
            kind,
            request.form.get("email") or "",
            request.form.get("password") or "",
            request.form.get("rol") or "operador",
            dias_demo=int(request.form.get("dias_demo") or 30),
            invitado_por=master_email,
            enviar_invitacion=request.form.get("enviar_invitacion") == "1",
            mail_tesoreria=request.form.get("mail_tesoreria") == "1",
            mail_petroleo=request.form.get("mail_petroleo") == "1",
            solo_lectura=request.form.get("solo_lectura") == "1",
        )

    if action == "reenviar_invitacion":
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        return tad.reenviar_invitacion(
            db,
            kind,
            uid,
            request.form.get("password") or "",
            master_email,
        )

    if action == "extender_prueba":
        if kind != "demo":
            return False, "Extender prueba solo aplica al DEMO Agrícola."
        try:
            uid = int(request.form.get("user_id") or 0)
        except ValueError:
            return False, "Usuario inválido."
        try:
            dias_demo = int(request.form.get("dias_demo") or 30)
        except (TypeError, ValueError):
            dias_demo = 30
        return tad.extender_prueba(
            db,
            kind,
            uid,
            dias=dias_demo,
            admin_email=master_email,
            enviar_aviso=request.form.get("enviar_aviso") == "1",
        )

    if action == "alertas_guardar":
        # Comercial: checkboxes separados acceso / pago (como mails en LC Usuarios).
        kwargs = {}
        if tenant.get("kind") == "comercial":
            kwargs["alerta_acceso"] = request.form.get("alerta_acceso") == "1"
            kwargs["alerta_pago"] = request.form.get("alerta_pago") == "1"
        return tad.save_mail_alertas(
            tenant.get("secrets") or "",
            request.form.get("correo_receptor") or "",
            **kwargs,
        )

    if action == "prorrateo_guardar":
        pcts: dict[str, float] = {}
        for key, val in request.form.items():
            if not key.startswith("pct_"):
                continue
            cc = key[4:].replace("_", " ")
            try:
                pcts[cc] = float(val or 0)
            except (TypeError, ValueError):
                return False, f"Porcentaje inválido en {cc}."
        # Prefer explicit cc list from current config to keep original names
        actual = tad.get_prorrateo_cc(db, kind)
        mapped: dict[str, float] = {}
        for row in actual.get("rows") or []:
            cc = row["cc"]
            key = "pct_" + cc.replace(" ", "_")
            raw = request.form.get(key)
            if raw is None:
                mapped[cc] = float(row.get("porcentaje") or 0)
            else:
                try:
                    mapped[cc] = float(raw)
                except (TypeError, ValueError):
                    return False, f"Porcentaje inválido en {cc}."
        if not mapped and pcts:
            mapped = pcts
        return tad.save_prorrateo_cc(db, kind, mapped)

    if action == "respaldo_enviar_datos":
        return tad.enviar_respaldo_ahora(tenant, tipo="datos", usuario=master_email)

    if action == "respaldo_enviar_codigo":
        if not tad.es_owner_codigo_rubro(
            tenant.get("slug") or "", tenant.get("producto") or ""
        ):
            return False, (
                "El envío de código se hace desde "
                f"{tad.label_owner_codigo_rubro(tenant.get('producto') or '')}."
            )
        return tad.enviar_respaldo_ahora(tenant, tipo="codigo", usuario=master_email)

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
        producto = (tenant.get("producto") if tenant else "") or ""
        slug = (tenant.get("slug") if tenant else "") or ""
        guardar_codigo = tad.es_owner_codigo_rubro(slug, producto)
        if ("activo_datos" in request.form) or ("activo_codigo" in request.form) or ("activo" not in request.form):
            activo_datos = request.form.get("activo_datos") == "1"
            activo_codigo = request.form.get("activo_codigo") == "1" if guardar_codigo else False
        else:
            activo_datos = request.form.get("activo") == "1"
            activo_codigo = activo_datos if guardar_codigo else False
        return tad.save_respaldo_config(
            db,
            request.form.get("email") or "",
            activo_datos or (activo_codigo if guardar_codigo else False),
            request.form.get("freq_datos") or "diario",
            request.form.get("freq_codigo") or "semanal",
            activo_datos=activo_datos,
            activo_codigo=activo_codigo,
            producto=producto,
            guardar_codigo=guardar_codigo,
            slug=slug,
        )

    return False, "Acción no reconocida."
