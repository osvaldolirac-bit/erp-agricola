"""Ámbito tenant El Espino — variedades / centros de costo del huerto."""
from __future__ import annotations

VARIEDADES_ESPINO = (
    "ROYAL DOWN",
    "SWEET ARYANA",
    "SANTINA",
)

# Superficie plantada por variedad (ha) — base del prorrateo en consola y costos.
SUPERFICIE_HA_ESPINO: dict[str, float] = {
    "SWEET ARYANA": 1.0,
    "ROYAL DOWN": 1.5,
    "SANTINA": 4.5,
}

# CC de bodega Espino (stock compartido, distinto de cuarteles Libro de Campo).
BODEGA_CC_ESPINO = "EL ESPINO"

# Sector Libro de Campo antes del desglose por variedad (apps 1–5, etc.).
LEGADO_SECTOR_LC_ESPINO = "CEREZOS"

_VARIEDADES_UPPER = {v.upper(): v for v in VARIEDADES_ESPINO}


def cuarteles_espino() -> list[str]:
    return list(VARIEDADES_ESPINO)


def prorrateo_pct_espino() -> dict[str, float]:
    """Porcentajes de prorrateo según superficie ha (suma 100 %)."""
    total_ha = sum(SUPERFICIE_HA_ESPINO.get(v, 0.0) for v in VARIEDADES_ESPINO)
    if total_ha <= 0:
        n = len(VARIEDADES_ESPINO)
        base = round(100.0 / n, 2)
        out = {v: base for v in VARIEDADES_ESPINO[:-1]}
        out[VARIEDADES_ESPINO[-1]] = round(100.0 - sum(out.values()), 2)
        return out
    pcts = {
        v: round(100.0 * SUPERFICIE_HA_ESPINO.get(v, 0.0) / total_ha, 2)
        for v in VARIEDADES_ESPINO[:-1]
    }
    pcts[VARIEDADES_ESPINO[-1]] = round(100.0 - sum(pcts.values()), 2)
    return pcts


def es_cuartel_espino(nombre: str) -> bool:
    return (nombre or "").strip().upper() in _VARIEDADES_UPPER


def normalizar_cuartel_espino(nombre: str) -> str:
    key = (nombre or "").strip().upper()
    return _VARIEDADES_UPPER.get(key, "")


def cuarteles_espino_sql_in() -> tuple[str, ...]:
    """Sectores Libro de Campo Espino (variedades + legado bodega)."""
    return tuple({*VARIEDADES_ESPINO, BODEGA_CC_ESPINO})


def sectores_libro_campo_espino() -> frozenset[str]:
    """Sectores válidos en historial / desfase LC El Espino (incluye legado CEREZOS)."""
    return frozenset(
        {v.upper() for v in (*VARIEDADES_ESPINO, BODEGA_CC_ESPINO, LEGADO_SECTOR_LC_ESPINO)}
    )
