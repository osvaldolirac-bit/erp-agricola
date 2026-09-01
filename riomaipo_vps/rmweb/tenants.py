"""Tenants del producto Comercial (/comercial)."""
from __future__ import annotations

import os
from typing import Any

_DATA = os.environ.get("COMERCIAL_DATA_DIR", "/root/riomaipo/data").strip() or "/root/riomaipo/data"

TENANTS: dict[str, dict[str, Any]] = {
    "riomaipo": {
        "slug": "riomaipo",
        "nombre": "Río Maipo",
        "nombre_erp": "Río Maipo",
        "descripcion": "Cotizaciones y cobranza — construcción",
        "db": os.environ.get("RIOMAIPO_DB", f"{_DATA}/riomaipo_erp.db"),
        "secrets": os.environ.get(
            "RIOMAIPO_SECRETS", "/root/riomaipo/secrets_riomaipo.toml"
        ),
        "empresa_default": {
            "rut": "76.073.876-K",
            "razon_social": "Constructora Rio Maipo S.A.",
            "telefono": "56990798992",
            "email": "osvaldolira@constructorariomaipo.cl",
            "direccion": "Parcela El Sauce lote 4, Paine",
            "region": "Metropolitana",
            "pais": "Chile",
        },
    },
    "comercial-lc": {
        "slug": "comercial-lc",
        "nombre": "Comercial LC",
        "nombre_erp": "Comercial LC",
        "descripcion": "Cotizaciones y cobranza — agrícola (provisorio)",
        "db": os.environ.get("COMERCIAL_LC_DB", f"{_DATA}/comercial_lc.db"),
        "secrets": os.environ.get(
            "COMERCIAL_LC_SECRETS", "/root/riomaipo/secrets_comercial_lc.toml"
        ),
        "empresa_default": {
            "rut": "",
            "razon_social": "Comercial LC",
            "telefono": "",
            "email": "",
            "direccion": "",
            "region": "Metropolitana",
            "pais": "Chile",
        },
    },
    "comercial-demo": {
        "slug": "comercial-demo",
        "nombre": "DEMO Comercial",
        "nombre_erp": "DEMO Comercial",
        "descripcion": "Pruebas e invitaciones — Comercial",
        "es_demo": True,
        "rubro": "comercial",
        "db": os.environ.get("COMERCIAL_DEMO_DB", f"{_DATA}/comercial_demo.db"),
        "secrets": os.environ.get(
            "COMERCIAL_DEMO_SECRETS", "/root/riomaipo/secrets_comercial_demo.toml"
        ),
        "empresa_default": {
            "rut": "76.000.000-0",
            "razon_social": "DEMO Comercial",
            "telefono": "",
            "email": "",
            "direccion": "",
            "region": "Metropolitana",
            "pais": "Chile",
        },
    },
    "taller-demo": {
        "slug": "taller-demo",
        "nombre": "DEMO Taller Automotriz",
        "nombre_erp": "DEMO Taller Automotriz",
        "descripcion": "Pruebas — Taller automotriz (cotizaciones + OT)",
        "es_demo": True,
        "rubro": "taller",
        "db": os.environ.get("TALLER_DEMO_DB", f"{_DATA}/taller_demo.db"),
        "secrets": os.environ.get(
            "TALLER_DEMO_SECRETS", "/root/riomaipo/secrets_taller_demo.toml"
        ),
        "empresa_default": {
            "rut": "76.000.000-1",
            "razon_social": "DEMO Taller Automotriz",
            "telefono": "",
            "email": "",
            "direccion": "",
            "region": "Metropolitana",
            "pais": "Chile",
        },
    },
}

_TENANT_ORDER = ("riomaipo", "comercial-lc", "comercial-demo", "taller-demo")


def list_tenants() -> list[dict[str, Any]]:
    return [TENANTS[k] for k in _TENANT_ORDER if k in TENANTS]


def get_tenant(slug: str | None) -> dict[str, Any] | None:
    if not slug:
        return None
    return TENANTS.get(str(slug).strip().lower())


def es_demo(slug: str | None) -> bool:
    ten = get_tenant(slug)
    return bool(ten and ten.get("es_demo"))


def rubro(slug: str | None) -> str:
    ten = get_tenant(slug)
    return str((ten or {}).get("rubro") or "comercial").strip().lower()


# Módulos ocultos por rubro (menú lateral y acceso directo por URL).
_MODULOS_OCULTOS_POR_RUBRO: dict[str, frozenset[str]] = {
    "taller": frozenset({"arriendos", "mercadolibre"}),
}

# Módulos visibles solo en ciertos rubros.
_MODULOS_EXCLUSIVOS: dict[str, frozenset[str]] = {
    "taller_ot": frozenset({"taller"}),
}


def modulo_visible(slug: str | None, modulo: str) -> bool:
    """Indica si un módulo del menú lateral aplica al tenant."""
    mod = str(modulo or "").strip().lower()
    if not mod:
        return False
    r = rubro(slug)
    if mod in _MODULOS_OCULTOS_POR_RUBRO.get(r, frozenset()):
        return False
    exclusivo = _MODULOS_EXCLUSIVOS.get(mod)
    if exclusivo is not None:
        return r in exclusivo
    return True
