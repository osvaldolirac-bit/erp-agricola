from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import abort, flash, g, redirect, request, session, url_for

from demo_web.auth.login_next import stash_login_next
from demo_web.auth.user_db import fetch_session_row
from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app


def _registrar_acceso_sesion(demo, email: str, modulo: str = "") -> None:
    """Equivalente Flask de anclaje_sesion_definitivo: bitácora ACCESO + pulse usuario."""
    from demo_web.services.erp_loader import get_erp_app
    from flask import session

    # Ingreso desde Super Consola: no contaminar la bitácora del tenant.
    if session.get("from_master_console"):
        return

    try:
        from demo_web.services.mantenimiento import bitacora_erp_activa

        slug = session.get("tenant_slug") or (
            "concepcion" if get_erp_app() == "concepcion" else "demo"
        )
        if not bitacora_erp_activa(slug):
            return
    except Exception:
        return

    app_tag = "lc" if get_erp_app() == "concepcion" else "demo"
    tag = f"acceso_v1154_{app_tag}_{email}_{demo.hora_chile().strftime('%Y%m%d')}"
    if session.get(tag):
        return
    try:
        conn = demo.conectar_db()
        f_h = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
        detalle = "Sesión Detectada (Flask LC)" if app_tag == "lc" else "Sesión Detectada (Flask demo)"
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (email, "ACCESO", detalle, f_h),
        )
        conn.commit()
        try:
            from erp_sesiones_usuarios import registrar_pulse_usuario

            registrar_pulse_usuario(conn, email, modulo or "")
        except Exception:
            pass
        conn.close()
        session[tag] = True
    except Exception:
        pass


def _current_user() -> dict | None:
    email = session.get("email")
    if not email:
        return None
    return {
        "email": email,
        "rol": session.get("rol", "operador"),
    }


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if not user or not session.get("tenant_slug"):
            # Tras restaurar mantención no reenviar a la actividad previa.
            try:
                from flask import current_app
                from demo_web.services.mantenimiento import (
                    acceso_login_path,
                    en_post_mantenimiento,
                )

                slug = session.get("tenant_slug") or ""
                if slug and en_post_mantenimiento(slug):
                    return redirect(acceso_login_path(current_app))
            except Exception:
                pass
            stash_login_next(request_path())
            return redirect(url_for("auth.login"))
        demo = get_demo_module()
        conn = demo.conectar_db()
        try:
            row = fetch_session_row(conn, user["email"])
        finally:
            conn.close()
        if not row:
            session.clear()
            flash("Usuario no encontrado.", "danger")
            return redirect(url_for("auth.login"))
        rol = demo.normalizar_rol_usuario(row[0], user["email"])
        session["rol"] = rol
        fecha_expira = row[1] if len(row) > 1 else None
        solo_lectura = bool(row[2]) if len(row) > 2 else False
        if rol == "lector":
            solo_lectura = True
        session["solo_lectura"] = solo_lectura
        if fecha_expira and not demo.usuario_prueba_vigente(fecha_expira):
            session.clear()
            flash("Su periodo de prueba ha finalizado.", "warning")
            return redirect(url_for("auth.login"))
        bind_user_session(user["email"], rol, solo_lectura=session.get("solo_lectura", False))
        g.user = {"email": user["email"], "rol": rol}
        g.demo = demo
        _registrar_acceso_sesion(demo, user["email"], request.endpoint or "")
        return view(*args, **kwargs)

    return wrapped


def module_required(module_key: str):
    def deco(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from flask import session
            from demo_web.tenants import get_tenant

            tenant_slug = (getattr(g, "tenant_slug", None) or session.get("tenant_slug") or "").strip().lower()
            if module_key == "Espino" and tenant_slug == "demo":
                abort(404)
            demo = g.demo
            bind_user_session(g.user["email"], g.user["rol"])
            tenant = get_tenant(tenant_slug)
            if tenant and tenant.get("kind") == "globalgap":
                # Menú GlobalGAP se arma en build_menu(); app_demo no incluye Soporte en opts.
                if module_key not in {"GlobalGAP", "Soporte", "Manual"}:
                    abort(403)
                return view(*args, **kwargs)
            if not demo.puede_acceder_modulo(module_key):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return deco


def request_path() -> str:
    from flask import request

    prefix = request.script_root or ""
    path = request.full_path if request.query_string else request.path
    if prefix and not path.startswith(prefix):
        return prefix + path
    return path


def build_menu(user_email: str, rol: str) -> list[dict]:
    from demo_web.tenants import get_tenant
    from flask import session

    tenant = get_tenant(session.get("tenant_slug"))
    if tenant and tenant.get("kind") == "globalgap":
        items = [
            {
                "label": "Panel consultor",
                "key": "PanelGlobalGAP",
                "endpoint": "globalgap_portal.panel",
                "icon": "bi-grid-1x2",
            },
            {
                "label": "Clientes",
                "key": "ClientesGlobalGAP",
                "endpoint": "globalgap_portal.clientes_list",
                "icon": "bi-people",
            },
            {
                "label": "Certificación",
                "key": "GlobalGAP",
                "endpoint": "modules.globalgap",
                "icon": "bi-patch-check",
            },
            {
                "label": "Soporte",
                "key": "Soporte",
                "endpoint": "modules.soporte",
                "icon": "bi-life-preserver",
            },
            {
                "label": "Manual",
                "key": "Manual",
                "endpoint": "modules.manual",
                "icon": "bi-book",
            },
        ]
        return items

    demo = get_demo_module()
    bind_user_session(user_email, rol)
    opts = demo.construir_menu_usuario(user_email, rol)
    modulos_menu = set(opts.values())
    badge_by_key: dict[str, int] = {}
    conn = demo.conectar_db()
    try:
        try:
            from erp_soporte import aplicar_badge_menu_soporte

            opts = aplicar_badge_menu_soporte(opts, conn, demo.es_admin)
        except Exception:
            pass
        from demo_web.services.sidebar_badges import conteos_sidebar

        badge_by_key = conteos_sidebar(conn, modulos_menu)
    finally:
        conn.close()

    slug_map = {
        "DASHBOARD": "modules.dashboard",
        "Compras": "modules.compras",
        "Tesoreria": "modules.tesoreria",
        "Flujo financiero": "modules.flujo",
        "Costos": "modules.costos",
        "RRHH": "modules.rrhh",
        "Campob": "modules.campob",
        "Espino": "modules.espino",
        "Libro de Campo": "modules.libro_campo",
        "Petróleo": "modules.petroleo",
        "Riego": "modules.riego",
        "Bodega": "modules.bodega",
        "Maquinaria": "modules.maquinaria",
        "GlobalGAP": "modules.globalgap",
        "Soporte": "modules.soporte",
        "Manual": "modules.manual",
        "Administracion": "modules.admin",
    }
    icon_map = {
        "DASHBOARD": "bi-grid-1x2",
        "Compras": "bi-cart3",
        "Tesoreria": "bi-bank",
        "Flujo financiero": "bi-graph-up-arrow",
        "Costos": "bi-calculator",
        "RRHH": "bi-people",
        "Campob": "bi-tree",
        "Espino": "bi-geo-alt",
        "Libro de Campo": "bi-journal-text",
        "Petróleo": "bi-fuel-pump",
        "Riego": "bi-droplet",
        "Bodega": "bi-box-seam",
        "Maquinaria": "bi-truck",
        "GlobalGAP": "bi-patch-check",
        "Soporte": "bi-life-preserver",
        "Manual": "bi-book",
        "Administracion": "bi-gear",
    }
    items = []
    for label, key in opts.items():
        endpoint = slug_map.get(key)
        if endpoint:
            item = {
                "label": label,
                "key": key,
                "endpoint": endpoint,
                "icon": icon_map.get(key, "bi-circle"),
            }
            if key in badge_by_key:
                item["badge_count"] = badge_by_key[key]
            items.append(item)
    return items
