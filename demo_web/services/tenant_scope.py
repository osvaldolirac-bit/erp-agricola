"""Ámbito operativo por tenant (cuarteles, especies). Fuente única para Flask."""
from __future__ import annotations

from typing import Any

ESPINO_CC = "Cerezos"
ESPINO_CCS = [ESPINO_CC]
RAZON_SOCIAL_ESPINO = "El Espino"
RAZONES_SOCIALES_ESPINO = [RAZON_SOCIAL_ESPINO]


def tenant_slug() -> str:
    try:
        from flask import g, has_request_context, session

        if has_request_context():
            slug = getattr(g, "tenant_slug", None) or session.get("tenant_slug")
            if slug:
                return str(slug).strip().lower()
    except Exception:
        pass
    return ""


def is_espino_tenant() -> bool:
    return tenant_slug() == "espino"


def centros_costo(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    return list(getattr(demo, "CENTROS_COSTO", []) or [])


def cuarteles_oficiales(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    return list(getattr(demo, "CUARTELES_OFICIALES", []) or [])


def cuarteles_prorrateo(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    return list(getattr(demo, "CUARTELES_PRORRATEO", []) or [])


def cuarteles_imputacion_directa(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    return list(getattr(demo, "CUARTELES_IMPUTACION_DIRECTA", []) or [])


def gap_especies(demo: Any) -> list[str]:
    if is_espino_tenant():
        return ["EL ESPINO"]
    return list(getattr(demo, "GAP_ESPECIES", []) or [])


def libro_campo_especies(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    return list(getattr(demo, "LIBRO_CAMPO_ESPECIES", []) or [])


def razones_sociales_compras(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(RAZONES_SOCIALES_ESPINO)
    return list(getattr(demo, "RAZONES_SOCIALES_COMPRAS", []) or [])


def razon_social_compras_default(demo: Any) -> str:
    razones = razones_sociales_compras(demo)
    return razones[0] if razones else "El Espino"


def cuarteles_gap_especie(demo: Any, especie: str) -> list[str]:
    if is_espino_tenant():
        return list(ESPINO_CCS)
    fn = getattr(demo, "cuarteles_gap_especie", None)
    if callable(fn):
        return list(fn(especie) or [])
    mapping = getattr(demo, "GAP_ESPECIE_CUARTELES", {}) or {}
    return list(mapping.get(especie, [])) + ["OTROS"]
