"""Mapa de módulos Flask por ERP (demo vs La Concepción)."""
from __future__ import annotations

from demo_web.services.erp_loader import get_erp_app

_BASE_MODULES: dict[str, tuple[str, str]] = {
    "dashboard": ("DASHBOARD", "modulo_dashboard"),
    "compras": ("Compras", "modulo_compras"),
    "tesoreria": ("Tesoreria", "modulo_tesoreria"),
    "petroleo": ("Petróleo", "modulo_petroleo"),
    "riego": ("Riego", "modulo_riego"),
    "bodega": ("Bodega", "modulo_bodega"),
    "libro-campo": ("Libro de Campo", "modulo_libro_campo"),
    "rrhh": ("RRHH", "modulo_rrhh"),
    "costos": ("Costos", "modulo_costos"),
    "flujo": ("Flujo financiero", "modulo_flujo_financiero"),
    "maquinaria": ("Maquinaria", "modulo_maquinaria"),
    "globalgap": ("GlobalGAP", "modulo_globalgap"),
    "soporte": ("Soporte", "modulo_soporte"),
    "admin": ("Administracion", "modulo_seguridad"),
    "manual": ("Manual", "modulo_manual"),
}


def get_modules() -> dict[str, tuple[str, str]]:
    mods = dict(_BASE_MODULES)
    mods["campob"] = ("Campob", "modulo_campob")
    # Espino: ruta activa (La Concepción); tenant demo lo bloquea en module_required.
    mods["espino"] = ("Espino", "modulo_espino")
    return mods
