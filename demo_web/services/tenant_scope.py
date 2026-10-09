"""Ámbito operativo por tenant (cuarteles, especies). Fuente única para Flask."""
from __future__ import annotations

from typing import Any

from demo_web.services.espino_scope import cuarteles_espino

RAZON_SOCIAL_ESPINO = "El Espino"
RAZONES_SOCIALES_ESPINO = [RAZON_SOCIAL_ESPINO]


def _espino_variedades_costo() -> list[str]:
    """Centros de costo operativos El Espino — solo variedades."""
    return list(cuarteles_espino())


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


def is_concepcion_tenant() -> bool:
    return tenant_slug() == "concepcion"


def centros_costo(demo: Any) -> list[str]:
    if is_espino_tenant():
        return _espino_variedades_costo()
    return list(getattr(demo, "CENTROS_COSTO", []) or [])


def cuarteles_oficiales(demo: Any) -> list[str]:
    if is_espino_tenant():
        return _espino_variedades_costo()
    return list(getattr(demo, "CUARTELES_OFICIALES", []) or [])


def cuarteles_prorrateo(demo: Any) -> list[str]:
    if is_espino_tenant():
        return _espino_variedades_costo()
    return list(getattr(demo, "CUARTELES_PRORRATEO", []) or [])


def cuarteles_imputacion_directa(demo: Any) -> list[str]:
    if is_espino_tenant():
        return _espino_variedades_costo()
    return list(getattr(demo, "CUARTELES_IMPUTACION_DIRECTA", []) or [])


def gap_especies(demo: Any) -> list[str]:
    if is_espino_tenant():
        return ["Cerezos"]
    return list(getattr(demo, "GAP_ESPECIES", []) or [])


def libro_campo_especies(demo: Any) -> list[str]:
    if is_espino_tenant():
        return ["Cerezos"]
    return list(getattr(demo, "LIBRO_CAMPO_ESPECIES", []) or [])


def razones_sociales_compras(demo: Any) -> list[str]:
    if is_espino_tenant():
        return list(RAZONES_SOCIALES_ESPINO)
    razones = list(getattr(demo, "RAZONES_SOCIALES_COMPRAS", []) or [])
    if is_concepcion_tenant():
        razones = [
            r for r in razones
            if (r or "").strip().casefold() != RAZON_SOCIAL_ESPINO.casefold()
        ]
    return razones


def razon_social_compras_default(demo: Any) -> str:
    razones = razones_sociales_compras(demo)
    if razones:
        return razones[0]
    return razon_social_default()


def razon_social_default() -> str:
    if is_espino_tenant():
        return RAZON_SOCIAL_ESPINO
    return "La Concepción"


def cuarteles_gap_especie(demo: Any, especie: str) -> list[str]:
    if is_espino_tenant():
        return _espino_variedades_costo()
    fn = getattr(demo, "cuarteles_gap_especie", None)
    if callable(fn):
        return list(fn(especie) or [])
    mapping = getattr(demo, "GAP_ESPECIE_CUARTELES", {}) or {}
    return list(mapping.get(especie, [])) + ["OTROS"]
