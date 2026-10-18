"""Filtros SQL/DataFrame para tenant LC (sin datos operativos El Espino en pantallas LC)."""
from __future__ import annotations

import pandas as pd

from demo_web.services.tenant_rules import excluir_razon_social_espino_en_queries
from demo_web.services.tenant_scope import RAZON_SOCIAL_ESPINO

CUARTEL_ESPINO_LC = "EL ESPINO"


def es_razon_social_espino_excluida(razon: str | None) -> bool:
    return (razon or "").strip().casefold() == RAZON_SOCIAL_ESPINO.casefold()


def sql_and_excluir_razon_social_espino(col: str = "razon_social", alias: str | None = None) -> str:
    if not excluir_razon_social_espino_en_queries():
        return ""
    col_ref = f"{alias}.{col}" if alias else col
    return f" AND TRIM(COALESCE({col_ref}, '')) != '{RAZON_SOCIAL_ESPINO}' "


def cuarteles_costos_lc(cuarteles: list[str] | None) -> list[str]:
    if not excluir_razon_social_espino_en_queries() or not cuarteles:
        return list(cuarteles or [])
    return [c for c in cuarteles if str(c).upper().strip() != CUARTEL_ESPINO_LC]


def filtrar_df_facturas_espino_lc(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if not excluir_razon_social_espino_en_queries() or df is None or df.empty:
        return df
    if "razon_social" not in df.columns:
        return df
    mask = ~df["razon_social"].astype(str).str.strip().map(es_razon_social_espino_excluida)
    return df.loc[mask].copy()
