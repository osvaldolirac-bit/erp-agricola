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
    """Ruta fija post-login → /m/stock-bodega (La Concepción)."""
    return f"{rubro_public_base()}/login/stock-bodega"
