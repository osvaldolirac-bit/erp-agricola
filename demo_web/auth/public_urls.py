"""URLs públicas estables para WhatsApp / celular (no dependen del Host de la petición)."""
from __future__ import annotations

import os

from flask import current_app


def rubro_public_base() -> str:
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
    return f"{base}{prefix}"


def url_publica_login_stock_bodega() -> str:
    """Link móvil LC con token (misma lógica que registro-riego / salida-petroleo)."""
    from demo_web.services.stock_bodega_link import url_publica

    return url_publica()
