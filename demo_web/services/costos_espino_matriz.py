"""Ajustes matriz Costos tenant El Espino (prorrateo CC legacy bodega)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from demo_web.services.espino_scope import (
    centros_costo_bodega_espino,
    cuarteles_espino,
    prorrateo_pct_espino,
)
from demo_web.services.lc_excluir_espino import _recomputar_cierre_matriz


def _split_monto(total: float, pcts: dict[str, float]) -> dict[str, float]:
    items = list(pcts.items())
    acc = 0.0
    out: dict[str, float] = {}
    for i, (cc, pct) in enumerate(items):
        if i == len(items) - 1:
            part = round(total - acc, 2)
        else:
            part = round(total * pct / 100.0, 2)
            acc += part
        if abs(part) >= 0.01:
            out[cc] = part
    return out


def _sumar_prorrateado(body: pd.DataFrame, rubro: str, monto: float, pcts: dict[str, float]) -> None:
    if not rubro or abs(monto) < 0.01:
        return
    partes = _split_monto(monto, pcts)
    mask = body["Rubro"] == rubro
    if not mask.any():
        return
    idx = body.index[mask][0]
    for cc, part in partes.items():
        if cc not in body.columns:
            continue
        body.at[idx, cc] = float(body.at[idx, cc] or 0) + part
    skip = {"Rubro", "TOTAL", "% Total"}
    cc_cols = [c for c in body.columns if c not in skip]
    body.at[idx, "TOTAL"] = sum(float(body.at[idx, c] or 0) for c in cc_cols)


def inyectar_prorrateo_legacy_cc(
    conn,
    demo: Any,
    matriz: pd.DataFrame | None,
    cuarteles: list[str],
    fi=None,
    ff=None,
) -> pd.DataFrame | None:
    """Reparte gastos en CC legacy (Cerezos / EL ESPINO) hacia variedades por ha."""
    if matriz is None or matriz.empty:
        return matriz

    legacy = centros_costo_bodega_espino()
    pcts = prorrateo_pct_espino()
    variedades = set(cuarteles_espino())
    if not legacy or not pcts or not variedades:
        return matriz

    cierre = {"TOTAL GASTO", "PRESUPUESTO", "SALDO"}
    body = matriz[~matriz["Rubro"].isin(cierre)].copy()
    filtro_m = ""
    params_m: tuple[Any, ...] = ()
    if fi and ff:
        filtro_m = " AND m.fecha BETWEEN ? AND ? "
        params_m = (str(fi), str(ff))

    legacy_sql = ",".join(f"'{x}'" for x in sorted(legacy))
    fn_rubro_prod = getattr(demo, "_rubro_costo_desde_producto", None)

    q_mov = f"""
        SELECT UPPER(TRIM(m.centro_costo)) AS cc,
               m.valor_imputado AS m,
               COALESCE(i.producto, '') AS producto,
               i.familia AS familia
        FROM movimientos m
        LEFT JOIN inventario i ON m.producto_id = i.id
        WHERE ABS(COALESCE(m.valor_imputado, 0)) > 0.01
          AND UPPER(TRIM(COALESCE(m.centro_costo, ''))) IN ({legacy_sql})
          {filtro_m}
    """
    for row in conn.execute(q_mov, params_m):
        rubro = "Insumos"
        if callable(fn_rubro_prod):
            try:
                rubro = fn_rubro_prod(conn, row[2], row[3]) or rubro
            except Exception:
                pass
        _sumar_prorrateado(body, rubro, float(row[1] or 0), pcts)

    filtro_p = filtro_m.replace("m.fecha", "fecha") if filtro_m else ""
    q_pet = f"""
        SELECT SUM(valor_imputado) AS m
        FROM petroleo
        WHERE tipo = 'Salida'
          AND ABS(COALESCE(valor_imputado, 0)) > 0.01
          AND UPPER(TRIM(COALESCE(centro_costo, ''))) IN ({legacy_sql})
          {filtro_p}
    """
    row_pet = conn.execute(q_pet, params_m).fetchone()
    if row_pet and float(row_pet[0] or 0) > 0.01:
        _sumar_prorrateado(body, "Petróleo", float(row_pet[0]), pcts)

    q_aj = f"""
        SELECT SUM(monto) AS m
        FROM ajustes_costos
        WHERE ABS(COALESCE(monto, 0)) > 0.01
          AND UPPER(TRIM(COALESCE(centro_costo, ''))) IN ({legacy_sql})
          {filtro_p}
    """
    row_aj = conn.execute(q_aj, params_m).fetchone()
    if row_aj and float(row_aj[0] or 0) > 0.01:
        _sumar_prorrateado(body, "Ajustes", float(row_aj[0]), pcts)

    ppto = matriz[matriz["Rubro"] == "PRESUPUESTO"]
    if not ppto.empty:
        body = pd.concat([body, ppto], ignore_index=True)
    return _recomputar_cierre_matriz(body)
