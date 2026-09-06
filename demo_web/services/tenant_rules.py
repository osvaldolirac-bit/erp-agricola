"""Reglas de negocio por tenant agrícola LC — fuente única de verdad.

Todo cambio en Compras, Tesorería, Flujo o UI multi-tenant debe alinearse aquí.
verify_tenant_parity.py y verify_espino.py fallan si el código diverge.

Matriz LC vs Espino (misma app, distintas reglas):
  concepcion: CxP neta, sin INT-*, excluye razón El Espino, flujo sin imputar gastado
  espino:     CxP bruta, con INT-*, solo El Espino, flujo imputa gastado contable
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Slugs agrícola LC operativos (mismo erp_app concepcion, distinta DB)
LC_TENANT_SLUGS = frozenset({"concepcion", "espino"})


@dataclass(frozen=True)
class TenantRuleSet:
    slug: str
    cxp_saldo_neto: bool
    cxp_incluye_documentos_int: bool
    excluir_razon_social_el_espino: bool
    flujo_imputar_gastado_contable: bool
    muestra_logo_erpmaster: bool
    pago_proveedor_desde_doc_ids: bool


CONCEPCION = TenantRuleSet(
    slug="concepcion",
    cxp_saldo_neto=True,
    cxp_incluye_documentos_int=False,
    excluir_razon_social_el_espino=True,
    flujo_imputar_gastado_contable=False,
    muestra_logo_erpmaster=True,
    pago_proveedor_desde_doc_ids=True,
)

ESPINO = TenantRuleSet(
    slug="espino",
    cxp_saldo_neto=False,
    cxp_incluye_documentos_int=True,
    excluir_razon_social_el_espino=False,
    flujo_imputar_gastado_contable=True,
    muestra_logo_erpmaster=True,
    pago_proveedor_desde_doc_ids=True,
)

_BY_SLUG: dict[str, TenantRuleSet] = {
    "concepcion": CONCEPCION,
    "espino": ESPINO,
}


def rules_for_slug(slug: str | None) -> TenantRuleSet | None:
    key = (slug or "").strip().lower()
    return _BY_SLUG.get(key)


def rules_for_request() -> TenantRuleSet | None:
    from demo_web.services.tenant_scope import tenant_slug

    return rules_for_slug(tenant_slug())


def cxp_usar_saldo_neto() -> bool:
    r = rules_for_request()
    return r.cxp_saldo_neto if r else True


def cxp_incluye_documentos_int() -> bool:
    r = rules_for_request()
    return r.cxp_incluye_documentos_int if r else False


def excluir_razon_social_espino_en_queries() -> bool:
    r = rules_for_request()
    return r.excluir_razon_social_el_espino if r else False


def flujo_imputar_gastado_contable() -> bool:
    r = rules_for_request()
    return r.flujo_imputar_gastado_contable if r else False


def muestra_logo_erpmaster(slug: str | None = None) -> bool:
    from demo_web.services.tenant_scope import tenant_slug

    r = rules_for_slug(slug or tenant_slug())
    return r.muestra_logo_erpmaster if r else False


def verify_implementation_errors() -> list[str]:
    """Comprueba que tesoreria/flujo/branding implementan estas reglas."""
    from unittest.mock import patch

    errors: list[str] = []

    def _check(slug: str, rule: TenantRuleSet, fn_patch: Callable) -> None:
        with fn_patch(slug):
            from demo_web.services.tesoreria_cxp import (
                saldo_factura_tesoreria,
                sql_solo_cxp_tesoreria,
                usar_saldo_cxp_neto_en_tesoreria,
            )
            from demo_web.services.lc_excluir_espino import excluir_razon_social_espino_en_lc

            if usar_saldo_cxp_neto_en_tesoreria() != rule.cxp_saldo_neto:
                errors.append(f"{slug}: cxp_saldo_neto esperado {rule.cxp_saldo_neto}")
            sql = sql_solo_cxp_tesoreria("f")
            has_int = "NOT GLOB 'INT-*'" in sql
            if has_int == rule.cxp_incluye_documentos_int:
                errors.append(f"{slug}: cxp_incluye_documentos_int esperado {rule.cxp_incluye_documentos_int}")
            if excluir_razon_social_espino_en_lc() != rule.excluir_razon_social_el_espino:
                errors.append(
                    f"{slug}: excluir_razon_social_el_espino esperado {rule.excluir_razon_social_el_espino}"
                )
            neto = saldo_factura_tesoreria(1000, 0, 800)
            esperado = 200.0 if rule.cxp_saldo_neto else 1000.0
            if abs(neto - esperado) > 0.01:
                errors.append(f"{slug}: saldo_factura_tesoreria esperado {esperado}, got {neto}")

            from demo_web.services.branding import tenant_shows_master_brand

            if tenant_shows_master_brand(slug) != rule.muestra_logo_erpmaster:
                errors.append(f"{slug}: muestra_logo_erpmaster esperado {rule.muestra_logo_erpmaster}")

    def _patch(slug: str):
        is_esp = slug == "espino"
        is_lc = slug == "concepcion"
        return patch.multiple(
            "demo_web.services.tenant_scope",
            tenant_slug=lambda: slug,
            is_espino_tenant=lambda: is_esp,
            is_concepcion_tenant=lambda: is_lc,
        )

    for slug, rule in _BY_SLUG.items():
        _check(slug, rule, lambda s=slug: _patch(s))

    # Flujo: debe usar tenant_rules
    try:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        flujo = (root / "services/native/flujo.py").read_text(encoding="utf-8")
        if "imputar_gastado_contable=flujo_imputar_gastado_contable()" not in flujo:
            errors.append("flujo.py debe usar imputar_gastado_contable=flujo_imputar_gastado_contable()")
    except OSError as exc:
        errors.append(f"flujo.py no legible: {exc}")

    # Tesorería: pago por doc_ids (anti stale proveedor)
    try:
        from demo_web.services.native import tesoreria as teso

        if not callable(getattr(teso, "_proveedor_unico_desde_ids", None)):
            errors.append("tesoreria.py falta _proveedor_unico_desde_ids")
    except ImportError as exc:
        errors.append(f"tesoreria import: {exc}")

    # Logo embebido en repo
    bundled = Path(__file__).resolve().parents[1] / "static/img/logo_erpmaster.svg"
    if not bundled.is_file():
        errors.append(f"falta logo embebido: {bundled}")

    return errors
