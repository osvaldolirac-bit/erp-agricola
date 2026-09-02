"""Registro de tenants del rubro agrícola (un proceso, varias DB)."""
from __future__ import annotations

import os
from typing import Any


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


# Rubro: pantalla de acceso común
RUBRO_SLUG = "agricola"
RUBRO_TITLE = "ERP Agrícola"
RUBRO_BRAND = "ERP MASTER"
RUBRO_SUBTITLE = "Gestión integral para operaciones del campo"
RUBRO_PREFIX = _env("ERP_DEMO_URL_PREFIX", "/agricola") or "/agricola"


def _build_tenants() -> dict[str, dict[str, Any]]:
    return {
        "concepcion": {
            "slug": "concepcion",
            "erp_app": "concepcion",
            "kind": "lc",
            "nombre": "La Concepción",
            "nombre_erp": "ERP Agrícola La Concepción",
            "db": _env("ERP_LC_DB", "/root/erp_concepcion_v6.db"),
            "secrets": _env("ERP_LC_SECRETS", _env("ERP_SECRETS", "/root/.streamlit/secrets.toml")),
            "descripcion": "Soc. Agrícola La Concepción",
        },
        "espino": {
            "slug": "espino",
            "erp_app": "concepcion",
            "kind": "lc",
            "nombre": "El Espino",
            "nombre_erp": "ERP Agrícola El Espino",
            "db": _env("ERP_ESPINO_DB", "/root/espino/erp_espino.db"),
            "secrets": _env("ERP_ESPINO_SECRETS", "/root/espino/.streamlit/secrets.toml"),
            "descripcion": "ERP Agrícola El Espino",
        },
        "demo": {
            "slug": "demo",
            "erp_app": "demo",
            "kind": "demo",
            "nombre": "DEMO Agrícola",
            "db": _env("ERP_DEMO_DB", "/root/demo/erp_demo.db"),
            "secrets": _env("ERP_DEMO_SECRETS", "/root/demo/.streamlit/secrets.toml"),
            "descripcion": "Entorno de prueba e invitaciones",
        },
        "globalgap": {
            "slug": "globalgap",
            "erp_app": "demo",
            "kind": "globalgap",
            "nombre": "GlobalGAP Consultor",
            "db": _env("ERP_GLOBALGAP_DB", "/root/globalgap/erp_globalgap.db"),
            "secrets": _env("ERP_GLOBALGAP_SECRETS", "/root/globalgap/.streamlit/secrets.toml"),
            "descripcion": "Certificación multi-cliente · consultor",
        },
    }


TENANTS: dict[str, dict[str, Any]] = _build_tenants()


def list_tenants() -> list[dict[str, Any]]:
    return [TENANTS[k] for k in ("concepcion", "espino", "demo", "globalgap") if k in TENANTS]


def get_tenant(slug: str | None) -> dict[str, Any] | None:
    if not slug:
        return None
    return TENANTS.get(str(slug).strip().lower())


def reload_tenants() -> None:
    """Relee env (útil en tests)."""
    global TENANTS
    TENANTS = _build_tenants()
