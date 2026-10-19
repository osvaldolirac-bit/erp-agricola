"""Reglas de negocio por tenant agrícola — fuente única para flags LC/Espino.

Al agregar un tercer tenant: extender LC_TENANT_SLUGS, TenantRuleSet y verify_tenant_registry_errors.
"""
from __future__ import annotations

from dataclasses import dataclass

# Mismo erp_app, distinta SQLite (multi-tenant en un proceso).
LC_TENANT_SLUGS = frozenset({"concepcion", "espino"})


@dataclass(frozen=True)
class TenantRuleSet:
    slug: str
    excluir_razon_social_el_espino: bool
    flujo_imputar_gastado_contable: bool


CONCEPCION = TenantRuleSet(
    slug="concepcion",
    excluir_razon_social_el_espino=True,
    flujo_imputar_gastado_contable=False,
)
ESPINO = TenantRuleSet(
    slug="espino",
    excluir_razon_social_el_espino=False,
    flujo_imputar_gastado_contable=True,
)

_BY_SLUG: dict[str, TenantRuleSet] = {
    "concepcion": CONCEPCION,
    "espino": ESPINO,
}


def rules_for_slug(slug: str | None) -> TenantRuleSet | None:
    return _BY_SLUG.get((slug or "").strip().lower())


def rules_for_request() -> TenantRuleSet | None:
    from demo_web.services.tenant_scope import tenant_slug

    return rules_for_slug(tenant_slug())


def flujo_imputar_gastado_contable() -> bool:
    r = rules_for_request()
    if r is not None:
        return r.flujo_imputar_gastado_contable
    return False


def excluir_razon_social_espino_en_queries() -> bool:
    r = rules_for_request()
    if r is not None:
        return r.excluir_razon_social_el_espino
    from demo_web.services.tenant_scope import is_concepcion_tenant

    return is_concepcion_tenant()


def verify_tenant_registry_errors() -> list[str]:
    """CI: tenants LC registrados y aislados por BD."""
    from demo_web.tenants import TENANTS, get_tenant

    errors: list[str] = []
    dbs: dict[str, str] = {}
    for slug in LC_TENANT_SLUGS:
        t = get_tenant(slug)
        if not t:
            errors.append(f"Falta tenants.py slug={slug}")
            continue
        db = (t.get("db") or "").strip()
        if not db:
            errors.append(f"{slug}: sin db")
        elif db in dbs.values():
            prev = next(k for k, v in dbs.items() if v == db)
            errors.append(f"{slug} comparte db con {prev}: {db}")
        else:
            dbs[slug] = db
        if not (t.get("secrets") or "").strip():
            errors.append(f"{slug}: sin secrets")
        if t.get("erp_app") not in ("concepcion", "demo"):
            errors.append(f"{slug}: erp_app inesperado {t.get('erp_app')}")
    for slug in ("demo", "globalgap"):
        if slug not in TENANTS:
            errors.append(f"Falta tenants.py slug={slug}")
    return errors
