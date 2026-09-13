"""Ámbito tenant El Espino — variedades / centros de costo del huerto."""
from __future__ import annotations

VARIEDADES_ESPINO = (
    "ROYAL DOWN",
    "SWEET ARYANA",
    "SANTINA",
)

# CC de bodega Espino (stock compartido, distinto de cuarteles Libro de Campo).
BODEGA_CC_ESPINO = "EL ESPINO"

_VARIEDADES_UPPER = {v.upper(): v for v in VARIEDADES_ESPINO}


def cuarteles_espino() -> list[str]:
    return list(VARIEDADES_ESPINO)


def es_cuartel_espino(nombre: str) -> bool:
    return (nombre or "").strip().upper() in _VARIEDADES_UPPER


def normalizar_cuartel_espino(nombre: str) -> str:
    key = (nombre or "").strip().upper()
    return _VARIEDADES_UPPER.get(key, "")


def cuarteles_espino_sql_in() -> tuple[str, ...]:
    """Sectores Libro de Campo Espino (variedades + legado bodega)."""
    return tuple({*VARIEDADES_ESPINO, BODEGA_CC_ESPINO})
