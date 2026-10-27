"""Tenant en links públicos (registro riego, salida petróleo, cosecha): ?tenant= gana sobre sesión."""
from __future__ import annotations

from flask import request, session

# Endpoints sin login donde el operador abre un URL con token (WhatsApp / QR).
_PUBLIC_LINK_ENDPOINTS = frozenset(
    {
        "registro_riego.formulario",
        "salida_petroleo.formulario",
        "stock_bodega_link.formulario",
        "stock_bodega_link.kardex",
        "stock_bodega_link.pdf_kardex",
        "auth.cosecha_formulario",
    }
)


def tenant_slug_from_query() -> str:
    return (request.args.get("tenant") or request.form.get("tenant") or "").strip().lower()


def tenant_slug_for_request(endpoint: str | None = None) -> str | None:
    ep = endpoint if endpoint is not None else (request.endpoint or "")
    if ep == "registro_riego.formulario":
        # HYDRA / link riego vive solo en La Concepción (token y sectores en esa DB).
        q = tenant_slug_from_query()
        return "demo" if q == "demo" else "concepcion"
    if ep in _PUBLIC_LINK_ENDPOINTS:
        q = tenant_slug_from_query()
        if q:
            return q
        # Links WhatsApp antiguos sin ?tenant=: no heredar sesión web (p. ej. Espino).
        return "concepcion"
    slug = session.get("tenant_slug")
    return str(slug).strip().lower() if slug else None
