"""Carga app_demo / app_concepcion según tenant de la petición (rubro agrícola)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from demo_web.services.erp_compat import patch_erp_module
from demo_web.services.streamlit_mock import bind_demo_session, clear_demo_session, install_streamlit_mock
from demo_web.tenants import TENANTS, get_tenant, list_tenants

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
    # Fallback seguro solo fuera de request (CLI / init)
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


def _load_module(erp_app: str) -> Any:
    install_streamlit_mock()
    if erp_app == "concepcion":
        import app_concepcion as erp  # noqa: WPS433
    else:
        import app_demo as erp  # noqa: WPS433
    patch_erp_module(erp, erp_app)
    _wrap_registrar_accion(erp)
    if erp_app == "concepcion":
        _capture_lc_defaults(erp)
    return erp


def _apply_espino_tenant_overrides(erp: Any) -> None:
    """Tenant El Espino: un solo cuartel Cerezos y ámbito GlobalGAP propio."""
    erp.CENTROS_COSTO = ["Cerezos"]
    erp.CUARTELES_OFICIALES = ["Cerezos"]
    erp.CUARTELES_PRORRATEO = ["Cerezos"]
    erp.CUARTELES_IMPUTACION_DIRECTA = ["Cerezos"]
    erp.PRORRATEO_CC_DEFAULT = {"Cerezos": 100.0}
    erp.GAP_ESPECIES = ["EL ESPINO"]
    erp.GAP_ESPECIE_CUARTELES = {"EL ESPINO": ["Cerezos"]}
    erp.LIBRO_CAMPO_ESPECIES = ["Cerezos"]
    erp.RAZONES_SOCIALES_COMPRAS = ["El Espino"]


def _apply_tenant_config(erp: Any, t: dict[str, Any]) -> None:
    erp.NOMBRE_DB = t["db"]
    erp.SECRETS_PATH = t["secrets"]
    nombre_erp = (t.get("nombre_erp") or "").strip()
    if nombre_erp:
        erp.NOMBRE_ERP = nombre_erp
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
