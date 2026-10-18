"""Reglas de negocio por tenant (flags compartidos por módulos LC)."""
from __future__ import annotations


def excluir_razon_social_espino_en_queries() -> bool:
    """Tenant La Concepción: no mezclar facturas/imputaciones de razón social El Espino."""
    from demo_web.services.tenant_scope import is_concepcion_tenant

    return is_concepcion_tenant()
