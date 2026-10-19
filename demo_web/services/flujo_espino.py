"""Normalización ingresos flujo tenant El Espino (legacy Cerezos → variedades)."""
from __future__ import annotations

from demo_web.services.espino_scope import (
    es_cc_ingreso_flujo_legacy,
    fold_legacy_ingresos_flujo_en_variedades,
)


def normalizar_mapa_ingresos_cc(ing: dict, cuarteles: list[str]) -> dict:
    """Convierte filas legacy en flujo_ingresos_cc a prorrateo por variedad."""
    centros = [str(c).strip() for c in (cuarteles or []) if str(c or "").strip()]
    if not centros:
        return dict(ing or {})

    ing_por_cc: dict[str, dict[tuple[int, int], float]] = {}
    for (cc, anio, mes), monto in (ing or {}).items():
        if es_cc_ingreso_flujo_legacy(str(cc)):
            continue
        ing_por_cc.setdefault(str(cc), {})[(int(anio), int(mes))] = float(monto or 0)

    ing_por_cc = fold_legacy_ingresos_flujo_en_variedades(ing or {}, ing_por_cc, centros)
    out: dict[tuple[str, int, int], float] = {}
    for cc, buckets in ing_por_cc.items():
        for (anio, mes), monto in buckets.items():
            out[(cc, anio, mes)] = float(monto or 0)
    return out
