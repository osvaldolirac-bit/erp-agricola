"""Clientes del cron de respaldo de datos — tenants agrícola + otros rubros en el VPS."""
from __future__ import annotations

from typing import Any

from demo_web.tenants import list_tenants

PRODUCTO_AGRICOLA = "agricola"

# Rubros comercial / constructora (no están en demo_web.tenants del rubro agrícola).
CLIENTES_OTROS_RUBROS: list[dict[str, Any]] = [
    {
        "slug": "riomaipo",
        "nombre": "Río Maipo",
        "db": "/root/riomaipo/data/riomaipo_erp.db",
        "secrets": "/root/riomaipo/secrets_riomaipo.toml",
        "producto": "comercial",
    },
    {
        "slug": "comercial_lc",
        "nombre": "Comercial LC",
        "db": "/root/riomaipo/data/comercial_lc.db",
        "secrets": "/root/riomaipo/secrets_comercial_lc.toml",
        "producto": "comercial",
    },
    {
        "slug": "comercial_demo",
        "nombre": "DEMO Comercial",
        "db": "/root/riomaipo/data/comercial_demo.db",
        "secrets": "/root/riomaipo/secrets_comercial_demo.toml",
        "producto": "comercial",
    },
    {
        "slug": "constructora_demo",
        "nombre": "DEMO Constructora",
        "db": "/root/constructora/data/constructora_demo.db",
        "secrets": "/root/constructora/secrets_constructora_demo.toml",
        "producto": "constructora",
    },
]


def _tenant_a_cliente(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": t["slug"],
        "nombre": (t.get("nombre_erp") or t.get("nombre") or t["slug"]).strip(),
        "db": t["db"],
        "secrets": t["secrets"],
        "producto": PRODUCTO_AGRICOLA,
    }


def clientes_respaldo_datos() -> list[dict[str, Any]]:
    """Lista unificada para erp_respaldo_cron (DATOS). Agrícola desde tenants.py."""
    agricola = [_tenant_a_cliente(t) for t in list_tenants()]
    return agricola + [dict(c) for c in CLIENTES_OTROS_RUBROS]


def dbs_por_slug() -> dict[str, str]:
    return {c["slug"]: c["db"] for c in clientes_respaldo_datos() if c.get("slug")}


def tenants_agricola_sin_respaldo_cron(clientes: list[dict[str, Any]] | None = None) -> list[str]:
    """Slugs de tenants agrícola cuya DB no está en la lista del cron."""
    clientes = clientes if clientes is not None else clientes_respaldo_datos()
    dbs = {c["db"] for c in clientes}
    faltan: list[str] = []
    for t in list_tenants():
        if t["db"] not in dbs:
            faltan.append(str(t["slug"]))
    return faltan
