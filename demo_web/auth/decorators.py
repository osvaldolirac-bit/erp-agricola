from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import abort, flash, g, redirect, request, session, url_for

from demo_web.auth.user_db import fetch_session_row
from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app


def _registrar_acceso_sesion(demo, email: str, modulo: str = "") -> None:
    """Equivalente Flask de anclaje_sesion_definitivo: bitácora ACCESO + pulse usuario."""
    from demo_web.services.erp_loader import get_erp_app
    from flask import session

    # Ingreso desde Super Consola: no contaminar la bitácora del tenant.
    if session.get("from_master_console"):
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
            return redirect(url_for("auth.login", next=request_path()))
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
            demo = g.demo
            bind_user_session(g.user["email"], g.user["rol"])
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
    demo = get_demo_module()
    bind_user_session(user_email, rol)
    opts = demo.construir_menu_usuario(user_email, rol)
    conn = demo.conectar_db()
    try:
        try:
            from erp_soporte import aplicar_badge_menu_soporte

            opts = aplicar_badge_menu_soporte(opts, conn, demo.es_admin)
        except Exception:
            pass
        try:
            from erp_maquinaria import aplicar_badge_menu_maquinaria

            opts = aplicar_badge_menu_maquinaria(opts, conn)
        except Exception:
            pass
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
        "Bodega": "modules.bodega",
        "Maquinaria": "modules.maquinaria",
        "GlobalGAP": "modules.globalgap",
        "Soporte": "modules.soporte",
        "Manual": "modules.manual",
        "Administracion": "modules.admin",
    }
    items = []
    for label, key in opts.items():
        endpoint = slug_map.get(key)
        if endpoint:
            items.append({"label": label, "key": key, "endpoint": endpoint})
    return items
