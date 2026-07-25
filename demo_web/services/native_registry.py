"""Despacho híbrido: módulos nativos Flask vs captura Streamlit."""
from __future__ import annotations

import importlib
from typing import Callable

from demo_web.services import module_runner as mr
from demo_web.services.erp_loader import get_erp_app

_BASE_NATIVE: dict[str, str] = {
    "dashboard": "demo_web.services.native.dashboard:view",
    "compras": "demo_web.services.native.compras:view",
    "tesoreria": "demo_web.services.native.tesoreria:view",
    "flujo": "demo_web.services.native.flujo:view",
    "costos": "demo_web.services.native.costos:view",
    "rrhh": "demo_web.services.native.rrhh:view",
    "libro-campo": "demo_web.services.native.libro_campo:view",
    "petroleo": "demo_web.services.native.petroleo:view",
    "bodega": "demo_web.services.native.bodega:view",
    "maquinaria": "demo_web.services.native.maquinaria:view",
    "globalgap": "demo_web.services.native.globalgap:view",
    "soporte": "demo_web.services.native.soporte:view",
    "manual": "demo_web.services.native.manual:view",
    "admin": "demo_web.services.native.administracion:view",
}


def _native_handlers() -> dict[str, str]:
    # Ambos disponibles; el menú del tenant decide qué mostrar.
    handlers = dict(_BASE_NATIVE)
    handlers["espino"] = "demo_web.services.native.espino:view"
    handlers["campob"] = "demo_web.services.native.campob:view"
    return handlers


def is_native(slug: str) -> bool:
    return slug in _native_handlers()


def run_native_or_capture(slug: str, user_email: str, user_rol: str):
    handler_path = _native_handlers().get(slug)
    if handler_path:
        mod_name, fn_name = handler_path.rsplit(":", 1)
        mod = importlib.import_module(mod_name)
        handler: Callable = getattr(mod, fn_name)
        return handler(user_email, user_rol)
    return mr.run_module_view(slug, user_email, user_rol)
