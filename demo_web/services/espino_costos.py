"""Costos El Espino — redistribuir gasto legacy CEREZOS → variedades por prorrateo."""
from __future__ import annotations

from typing import Any

import pandas as pd

from demo_web.services.espino_scope import LEGADO_SECTOR_LC_ESPINO, cuarteles_espino, prorrateo_pct_espino

RUBROS_CIERRE = frozenset({"TOTAL GASTO", "PRESUPUESTO", "SALDO"})


def cuarteles_vista_espino(demo: Any) -> list[str]:
    """CC visibles en Costos / Compras (solo variedades)."""
    _ = demo
    return list(cuarteles_espino())


def cuarteles_matriz_espino(demo: Any) -> list[str]:
    """CC para armar matriz: variedades + bucket legacy CEREZOS (ingesta histórica)."""
    out = cuarteles_vista_espino(demo)
    legacy = LEGADO_SECTOR_LC_ESPINO
    if legacy not in out:
        out.append(legacy)
    return out


def _pesos_prorrateo(conn, demo: Any) -> dict[str, float]:
    fn = getattr(demo, "cargar_prorrateo_cc", None)
    if callable(fn):
        try:
            pesos = fn(conn) or {}
            if pesos:
                variedades = cuarteles_espino()
                out = {v: float(pesos.get(v) or pesos.get(v.upper()) or 0) for v in variedades}
                total = sum(out.values())
                if total > 1e-9:
                    return out
        except Exception:
            pass
    return {k: v / 100.0 for k, v in prorrateo_pct_espino().items()}


def _legacy_cols(df: pd.DataFrame) -> list[str]:
    legacy_u = LEGADO_SECTOR_LC_ESPINO.upper()
    return [c for c in df.columns if str(c).upper().strip() == legacy_u]


def redistribuir_cerezos_en_matriz(
    matriz: pd.DataFrame | None,
    pesos: dict[str, float],
) -> pd.DataFrame | None:
    """Mueve gasto columna CEREZOS a variedades; elimina columna legacy."""
    if matriz is None or matriz.empty:
        return matriz
    df = matriz.copy()
    legacy_cols = _legacy_cols(df)
    if not legacy_cols:
        return _quitar_legacy_cols(df)

    variedades = [v for v in cuarteles_espino() if v in df.columns]
    if not variedades:
        variedades = list(cuarteles_espino())
        for v in variedades:
            if v not in df.columns:
                df[v] = 0.0

    norm = {v: float(pesos.get(v) or 0) for v in variedades}
    total_w = sum(norm.values())
    if total_w <= 1e-9:
        norm = {v: 1.0 / len(variedades) for v in variedades}
    else:
        norm = {v: norm[v] / total_w for v in variedades}

    for lc in legacy_cols:
        for idx in df.index:
            rubro = str(df.at[idx, "Rubro"])
            if rubro == "PRESUPUESTO":
                df.at[idx, lc] = 0.0
                continue
            amt = float(df.at[idx, lc] or 0)
            if abs(amt) < 0.01:
                continue
            for var, w in norm.items():
                df.at[idx, var] = float(df.at[idx, var] or 0) + amt * w
            df.at[idx, lc] = 0.0

    df = _quitar_legacy_cols(df)
    return _recomputar_totales_matriz(df, variedades)


def _quitar_legacy_cols(df: pd.DataFrame) -> pd.DataFrame:
    drop = _legacy_cols(df)
    if drop:
        df = df.drop(columns=drop, errors="ignore")
    return df


def _recomputar_totales_matriz(df: pd.DataFrame, variedades: list[str]) -> pd.DataFrame:
    skip = {"Rubro", "TOTAL", "% Total", *RUBROS_CIERRE}
    cc_cols = [c for c in df.columns if c not in skip and c in variedades]
    body = df[~df["Rubro"].isin(RUBROS_CIERRE)].copy()
    if cc_cols:
        body["TOTAL"] = body[cc_cols].sum(axis=1)
    cierre = df[df["Rubro"].isin(RUBROS_CIERRE)].copy()
    if cierre.empty:
        return body
    total_gasto = {c: float(body[c].sum()) for c in cc_cols + (["TOTAL"] if "TOTAL" in body.columns else [])}
    ppto_row = cierre[cierre["Rubro"] == "PRESUPUESTO"]
    ppto = (
        {c: float(ppto_row.iloc[0].get(c) or 0) for c in cc_cols + (["TOTAL"] if "TOTAL" in cierre.columns else [])}
        if not ppto_row.empty
        else {c: 0.0 for c in cc_cols}
    )
    if "TOTAL" in ppto:
        ppto["TOTAL"] = sum(ppto.get(c, 0) for c in cc_cols)
    saldo = {c: ppto.get(c, 0) - total_gasto.get(c, 0) for c in set(ppto) | set(total_gasto)}
    footer = pd.DataFrame(
        [
            {"Rubro": "TOTAL GASTO", **{c: total_gasto.get(c, 0) for c in cc_cols + ["TOTAL"]}},
            {"Rubro": "PRESUPUESTO", **{c: ppto.get(c, 0) for c in cc_cols + ["TOTAL"]}},
            {"Rubro": "SALDO", **{c: saldo.get(c, 0) for c in cc_cols + ["TOTAL"]}},
        ]
    )
    return pd.concat([body, footer], ignore_index=True)


def preparar_matriz_costos_espino(demo: Any, conn, matriz: pd.DataFrame | None) -> pd.DataFrame | None:
    """Redistribuye CEREZOS → variedades conservando total gasto."""
    pesos = _pesos_prorrateo(conn, demo)
    return redistribuir_cerezos_en_matriz(matriz, pesos)
