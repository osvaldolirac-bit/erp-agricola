"""Columnas de un ítem de cola Hydrawise. fert_json es la décima."""
from __future__ import annotations

from typing import Any


def partes_item(row: Any) -> tuple:
    """id, orden, relay_id, minutos, estado, run_inicio, run_fin, codigo, error, fert_json."""
    fert = row[9] if len(row) > 9 else ""
    return (
        int(row[0]),
        row[1],
        int(row[2]),
        float(row[3]),
        row[4],
        row[5],
        row[6],
        row[7],
        row[8],
        fert,
    )
