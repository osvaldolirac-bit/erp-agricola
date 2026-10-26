"""Carga app_demo / app_concepcion según tenant de la petición (rubro agrícola)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from demo_web.services.erp_compat import patch_erp_module
from demo_web.services.streamlit_mock import bind_demo_session, clear_demo_session, install_streamlit_mock
from demo_web.tenants import TENANTS, get_tenant, list_tenants, tenant_nombre_erp

_DEMO_WEB_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]

if (_DEMO_WEB_ROOT / "app_demo.py").exists() or (_DEMO_WEB_ROOT / "app_concepcion.py").exists():
    if str(_DEMO_WEB_ROOT) not in sys.path:
        sys.path.insert(0, str(_DEMO_WEB_ROOT))
elif (_REPO_ROOT / "app_demo.py").exists() or (_REPO_ROOT / "app_concepcion.py").exists():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

_erp_modules: dict[str, Any] = {}
_LC_DEFAULTS: dict[str, Any] | None = None


def _capture_lc_defaults(erp: Any) -> None:
    global _LC_DEFAULTS
    if _LC_DEFAULTS is not None:
        return
    _LC_DEFAULTS = {
        "CENTROS_COSTO": list(erp.CENTROS_COSTO),
        "CUARTELES_OFICIALES": list(erp.CUARTELES_OFICIALES),
        "CUARTELES_PRORRATEO": list(erp.CUARTELES_PRORRATEO),
        "CUARTELES_IMPUTACION_DIRECTA": list(erp.CUARTELES_IMPUTACION_DIRECTA),
        "PRORRATEO_CC_DEFAULT": dict(erp.PRORRATEO_CC_DEFAULT),
        "GAP_ESPECIES": list(erp.GAP_ESPECIES),
        "GAP_ESPECIE_CUARTELES": dict(erp.GAP_ESPECIE_CUARTELES),
        "LIBRO_CAMPO_ESPECIES": list(erp.LIBRO_CAMPO_ESPECIES),
        "RAZONES_SOCIALES_COMPRAS": list(getattr(erp, "RAZONES_SOCIALES_COMPRAS", []) or []),
    }


def _restore_lc_defaults(erp: Any) -> None:
    if _LC_DEFAULTS is None:
        return
    erp.CENTROS_COSTO = list(_LC_DEFAULTS["CENTROS_COSTO"])
    erp.CUARTELES_OFICIALES = list(_LC_DEFAULTS["CUARTELES_OFICIALES"])
    erp.CUARTELES_PRORRATEO = list(_LC_DEFAULTS["CUARTELES_PRORRATEO"])
    erp.CUARTELES_IMPUTACION_DIRECTA = list(_LC_DEFAULTS["CUARTELES_IMPUTACION_DIRECTA"])
    erp.PRORRATEO_CC_DEFAULT = dict(_LC_DEFAULTS["PRORRATEO_CC_DEFAULT"])
    erp.GAP_ESPECIES = list(_LC_DEFAULTS["GAP_ESPECIES"])
    erp.GAP_ESPECIE_CUARTELES = dict(_LC_DEFAULTS["GAP_ESPECIE_CUARTELES"])
    erp.LIBRO_CAMPO_ESPECIES = list(_LC_DEFAULTS["LIBRO_CAMPO_ESPECIES"])
    if _LC_DEFAULTS.get("RAZONES_SOCIALES_COMPRAS"):
        erp.RAZONES_SOCIALES_COMPRAS = list(_LC_DEFAULTS["RAZONES_SOCIALES_COMPRAS"])


def _apply_espino_tenant_overrides(erp: Any) -> None:
    """Tenant El Espino: el centro de costo vigente son las 3 variedades.

    Cerezos ya no es un CC seleccionable. Queda solo como especie del libro
    (cerezo) y como etiqueta histórica de bodega/flujo, no en estas listas.
    """
    from demo_web.services.espino_scope import VARIEDADES_ESPINO, prorrateo_pct_espino

    variedades = list(VARIEDADES_ESPINO)
    erp.CENTROS_COSTO = variedades
    erp.CUARTELES_OFICIALES = variedades
    # Imputación directa parte el monto en partes iguales. En El Espino el
    # criterio es la superficie de cada variedad (prorrateo_cc), así que van
    # solo al listado de prorrateo.
    erp.CUARTELES_PRORRATEO = variedades
    erp.CUARTELES_IMPUTACION_DIRECTA = []
    erp.PRORRATEO_CC_DEFAULT = prorrateo_pct_espino()
    erp.GAP_ESPECIES = ["EL ESPINO"]
    erp.GAP_ESPECIE_CUARTELES = {"EL ESPINO": variedades}
    erp.LIBRO_CAMPO_ESPECIES = ["Cerezos"]
    erp.RAZONES_SOCIALES_COMPRAS = ["El Espino"]


def _request_tenant_slug() -> str:
    try:
        from flask import g, has_request_context, session

        if has_request_context():
            slug = getattr(g, "tenant_slug", None) or session.get("tenant_slug")
            if slug:
                return str(slug).strip().lower()
    except Exception:
        pass
    return ""


def current_tenant() -> dict[str, Any] | None:
    slug = _request_tenant_slug()
    t = get_tenant(slug)
    if t:
        return t
    return TENANTS.get("concepcion") or next(iter(TENANTS.values()), None)


def get_erp_app() -> str:
    t = current_tenant()
    if t:
        return str(t.get("erp_app") or "demo")
    return (os.environ.get("ERP_APP") or "demo").strip().lower()


def _wrap_registrar_accion(erp: Any) -> None:
    """Respeta flag bitácora por tenant (Master puede activarla/desactivarla)."""
    if getattr(erp, "_bitacora_gate_wrapped", False):
        return
    original = getattr(erp, "registrar_accion", None)
    if not callable(original):
        return

    def registrar_accion(accion, detalle=""):  # noqa: ANN001
        slug = _request_tenant_slug()
        if not slug:
            slug = "concepcion" if get_erp_app() == "concepcion" else "demo"
        if slug == "demo":
            try:
                from demo_web.master_bitacora import log_master_bitacora
                from flask import session

                user = (session.get("email") or "sistema").strip() or "sistema"
                log_master_bitacora(slug, user, str(accion or "ACCION"), str(detalle or ""))
            except Exception:
                pass
        try:
            from demo_web.services.mantenimiento import bitacora_erp_activa

            if not bitacora_erp_activa(slug):
                return None
        except Exception:
            return None
        return original(accion, detalle)

    erp.registrar_accion = registrar_accion
    erp._bitacora_gate_wrapped = True


def _wrap_conectar_db(erp: Any) -> None:
    """Antes de abrir SQLite, reaplica DB y constantes del tenant activo."""
    if getattr(erp, "_conectar_db_tenant_wrapped", False):
        return
    original = erp.conectar_db

    def conectar_db(*args, **kwargs):  # noqa: ANN001
        t = current_tenant()
        if t:
            _apply_tenant_config(erp, t)
        return original(*args, **kwargs)

    erp.conectar_db = conectar_db
    erp._conectar_db_tenant_wrapped = True


def _wrap_clasificar_cc_espino(erp: Any) -> None:
    """El Espino prorratea por superficie aunque las listas del módulo se crucen.

    ``app_concepcion._clasificar_cc_seleccionados`` rechaza la variedad si está
    a la vez en imputación directa y en prorrateo, y si encuentra ``ESPINO_CCS``
    la parte en tercios. Esa función no va en el deploy. Acá se reemplaza: en
    El Espino la variedad va solo a prorrateo; La Concepción sigue igual.
    """
    if getattr(erp, "_clasificar_cc_espino_wrapped", False):
        return
    original = getattr(erp, "_clasificar_cc_seleccionados", None)
    if not callable(original):
        return
    erp._clasificar_cc_espino_wrapped = True

    def _clasificar_cc_seleccionados(seleccionados):  # noqa: ANN001
        from demo_web.services.tenant_scope import is_espino_tenant

        if is_espino_tenant():
            from demo_web.services.espino_scope import VARIEDADES_ESPINO

            sel = [str(c).strip().upper() for c in (seleccionados or []) if str(c).strip()]
            valid = {v.upper() for v in VARIEDADES_ESPINO}
            prorr = [c for c in sel if c in valid]
            invalid = [c for c in sel if c not in valid]
            return [], prorr, invalid
        return original(seleccionados)

    erp._clasificar_cc_seleccionados = _clasificar_cc_seleccionados


def _wrap_prestamo_rrhh(erp: Any) -> None:
    """El saldo del préstamo sale del libro mayor, no de la suma histórica.

    ``app_concepcion`` resta todos los descuentos del trabajador al único monto
    de la ficha. Esas funciones no van en el deploy. Acá se reemplazan para que
    la planilla y Streamlit abonen el préstamo vigente.
    """
    if getattr(erp, "_prestamo_rrhh_wrapped", False):
        return
    original_guardar = getattr(erp, "_guardar_remuneracion_mes", None)
    if not callable(original_guardar):
        return
    erp._prestamo_rrhh_wrapped = True

    def _info_prestamo_worker(conn, trabajador_id):  # noqa: ANN001
        from demo_web.services.prestamo_rrhh import info_prestamo

        return info_prestamo(conn, int(trabajador_id))

    def _saldo_disponible_descuento_remuneracion(conn, trabajador_id, mes, anio):  # noqa: ANN001
        from demo_web.services.prestamo_rrhh import saldo_disponible_mes

        return saldo_disponible_mes(conn, int(trabajador_id), mes, anio)

    def _actualizar_cuotas_pagadas_desde_descuentos(conn, trabajador_id):  # noqa: ANN001
        from demo_web.services.prestamo_rrhh import reflejar_cuotas_ficha

        reflejar_cuotas_ficha(conn, int(trabajador_id))

    def _guardar_remuneracion_mes(conn, trabajador_id, mes, anio, liquido_ganado, suple, descuento_prestamo):  # noqa: ANN001
        from demo_web.services.prestamo_rrhh import reflejar_cuotas_ficha, sincronizar_abono_mes

        resultado = original_guardar(
            conn, trabajador_id, mes, anio, liquido_ganado, suple, descuento_prestamo
        )
        if resultado and resultado[0]:
            sincronizar_abono_mes(conn, int(trabajador_id), mes, anio, float(descuento_prestamo or 0))
            reflejar_cuotas_ficha(conn, int(trabajador_id))
        return resultado

    erp._info_prestamo_worker = _info_prestamo_worker
    if callable(getattr(erp, "_saldo_disponible_descuento_remuneracion", None)):
        erp._saldo_disponible_descuento_remuneracion = _saldo_disponible_descuento_remuneracion
    if callable(getattr(erp, "_actualizar_cuotas_pagadas_desde_descuentos", None)):
        erp._actualizar_cuotas_pagadas_desde_descuentos = _actualizar_cuotas_pagadas_desde_descuentos
    erp._guardar_remuneracion_mes = _guardar_remuneracion_mes


def _apply_tenant_config(erp: Any, t: dict[str, Any]) -> None:
    erp.NOMBRE_DB = t["db"]
    erp.SECRETS_PATH = t["secrets"]
    erp.NOMBRE_ERP = tenant_nombre_erp(t, getattr(erp, "NOMBRE_ERP", None))
    slug = str(t.get("slug") or "").strip().lower()
    erp.TENANT_SLUG = slug or "concepcion"
    erp.TENANT_NOMBRE = (t.get("nombre") or slug or "concepcion").strip()
    if slug == "espino":
        _apply_espino_tenant_overrides(erp)
    elif str(t.get("erp_app") or "") == "concepcion":
        _restore_lc_defaults(erp)
    os.environ["ERP_DB"] = t["db"]
    os.environ["ERP_DEMO_DB"] = t["db"]
    os.environ["ERP_SECRETS"] = t["secrets"]
    os.environ["ERP_DEMO_SECRETS"] = t["secrets"]
    os.environ["ERP_APP"] = str(t.get("erp_app") or "demo")
    try:
        from demo_web.services.streamlit_mock import set_secrets_path

        set_secrets_path(t["secrets"])
    except Exception:
        pass


def _load_module(erp_app: str) -> Any:
    install_streamlit_mock()
    if erp_app == "concepcion":
        import app_concepcion as erp  # noqa: WPS433
    else:
        import app_demo as erp  # noqa: WPS433
    patch_erp_module(erp, erp_app)
    if erp_app == "concepcion":
        from demo_web.services.lc_imputacion_bruto import instalar_imputacion_bruta_lc

        instalar_imputacion_bruta_lc(erp)
    _wrap_registrar_accion(erp)
    if erp_app == "concepcion":
        _capture_lc_defaults(erp)
        _wrap_conectar_db(erp)
        _wrap_clasificar_cc_espino(erp)
        _wrap_prestamo_rrhh(erp)
    return erp


def get_erp_module() -> Any:
    t = current_tenant()
    erp_app = str((t or {}).get("erp_app") or get_erp_app())
    if erp_app not in _erp_modules:
        _erp_modules[erp_app] = _load_module(erp_app)
    erp = _erp_modules[erp_app]
    if t:
        _apply_tenant_config(erp, t)
    return erp


def get_erp_module_for(slug: str) -> Any:
    """Carga módulo ligado a un tenant concreto (login multi-DB)."""
    t = get_tenant(slug)
    if not t:
        raise KeyError(f"tenant desconocido: {slug}")
    erp_app = t["erp_app"]
    if erp_app not in _erp_modules:
        _erp_modules[erp_app] = _load_module(erp_app)
    erp = _erp_modules[erp_app]
    _apply_tenant_config(erp, t)
    return erp


def bind_tenant_context(slug: str | None) -> dict[str, Any] | None:
    """Fija g.tenant_slug y prepara módulo/DB para la petición."""
    from flask import g

    t = get_tenant(slug)
    g.tenant_slug = t["slug"] if t else None
    g.tenant = t
    if t:
        get_erp_module_for(t["slug"])
    return t


def invalidate_erp_module() -> None:
    _erp_modules.clear()


def init_erp_db() -> None:
    for t in list_tenants():
        erp = get_erp_module_for(t["slug"])
        if t["erp_app"] == "demo":
            try:
                erp.inicializar_db()
            except Exception:
                pass


def bind_user_session(email: str, rol: str, **extra: Any) -> Any:
    erp = get_erp_module()
    rol_norm = erp.normalizar_rol_usuario(rol, email) if hasattr(erp, "normalizar_rol_usuario") else rol
    session_extra = dict(extra)
    if get_erp_app() == "concepcion":
        conn = erp.conectar_db()
        try:
            try:
                row = conn.execute(
                    "SELECT COALESCE(solo_lectura,0) FROM usuarios WHERE lower(email)=lower(?)",
                    (email,),
                ).fetchone()
                solo_lectura = bool(row[0]) if row else False
            except Exception:
                solo_lectura = False
            session_extra["solo_lectura"] = solo_lectura or rol_norm == "lector"
        finally:
            conn.close()
    return bind_demo_session(email, rol_norm, **session_extra)


def clear_user_session() -> None:
    clear_demo_session()


# Alias histórico demo
get_demo_module = get_erp_module
invalidate_demo_module = invalidate_erp_module
init_demo_db = init_erp_db
