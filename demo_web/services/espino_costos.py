"""Costos El Espino — única fuente de verdad para matriz, dashboard, flujo y PDF."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from demo_web.services.espino_scope import LEGADO_SECTOR_LC_ESPINO, cuarteles_espino, prorrateo_pct_espino

RUBROS_CIERRE = frozenset({"TOTAL GASTO", "PRESUPUESTO", "SALDO"})


def es_espino_demo(demo: Any) -> bool:
    """Detecta tenant Espino con o sin contexto Flask (erp.TENANT_SLUG)."""
    slug = str(getattr(demo, "TENANT_SLUG", "") or "").strip().lower()
    if slug == "espino":
        return True
    try:
        from demo_web.services.tenant_scope import is_espino_tenant

        return is_espino_tenant()
    except Exception:
        return False


def cuarteles_vista_espino(demo: Any) -> list[str]:
    """CC visibles en Costos / Dashboard / Flujo (solo variedades)."""
    _ = demo
    return list(cuarteles_espino())


def cuarteles_matriz_espino(demo: Any) -> list[str]:
    """CC para ingesta matriz: variedades + bucket legacy CEREZOS."""
    out = cuarteles_vista_espino(demo)
    legacy = LEGADO_SECTOR_LC_ESPINO
    if legacy not in out:
        out.append(legacy)
    return out


@dataclass
class ResultadoMatrizEspino:
    matriz: pd.DataFrame | None
    det_fi: Any
    det_ff: Any
    cuarteles_vista: list[str]


def _matriz_raw(demo: Any):
    return getattr(demo, "_armar_matriz_costos_vista_b_raw", demo._armar_matriz_costos_vista_b)


def armar_matriz_costos_espino(
    demo: Any,
    conn,
    prorrateo_rrhh: dict,
    temporada: str,
    fi=None,
    ff=None,
    *,
    fi_rrhh=None,
    ff_rrhh=None,
    neto_facturas_iva: bool = True,
) -> pd.DataFrame | None:
    """ÚNICA entrada matriz Costos Espino (bucket CEREZOS + redistribución por ha)."""
    raw = _matriz_raw(demo)
    cuarteles = cuarteles_matriz_espino(demo)
    matriz = raw(
        conn,
        fi,
        ff,
        cuarteles,
        prorrateo_rrhh,
        temporada,
        fi_rrhh=fi_rrhh,
        ff_rrhh=ff_rrhh,
        neto_facturas_iva=neto_facturas_iva,
    )
    return preparar_matriz_costos_espino(demo, conn, matriz)


def armar_matriz_costos_espino_temporada(
    demo: Any,
    conn,
    prorrateo_rrhh: dict,
    temporada: str,
    fi,
    ff,
    es_vigente: bool,
) -> ResultadoMatrizEspino:
    """Matriz Espino con rango operativo de temporada (módulo Costos)."""
    if es_vigente:
        fi_cons, ff_cons = demo._rango_fechas_costos_consulta(conn, fi, ff, True)
        matriz = armar_matriz_costos_espino(
            demo, conn, prorrateo_rrhh, temporada,
            fi_cons, ff_cons, fi_rrhh=fi, ff_rrhh=ff,
        )
        return ResultadoMatrizEspino(matriz, fi_cons, ff_cons, cuarteles_vista_espino(demo))
    matriz = armar_matriz_costos_espino(
        demo, conn, prorrateo_rrhh, temporada,
        fi, ff, fi_rrhh=fi, ff_rrhh=ff,
    )
    return ResultadoMatrizEspino(matriz, fi, ff, cuarteles_vista_espino(demo))


def total_gasto_matriz_espino(matriz: pd.DataFrame | None, demo: Any) -> float:
    if matriz is None or matriz.empty:
        return 0.0
    fn = getattr(demo, "_total_gasto_general_matriz", None)
    if callable(fn):
        return float(fn(matriz) or 0)
    tg = matriz[matriz["Rubro"] == "TOTAL GASTO"]
    if tg.empty or "TOTAL" not in tg.columns:
        return 0.0
    return float(tg.iloc[0]["TOTAL"] or 0)


def totales_por_variedad_dataframe(matriz: pd.DataFrame | None, demo: Any) -> pd.DataFrame:
    """DataFrame Cuartel/Total para Dashboard y tablas auxiliares."""
    vista = cuarteles_vista_espino(demo)
    if matriz is None or matriz.empty:
        return pd.DataFrame({"Cuartel": vista, "Total": [0.0] * len(vista)})
    tg = matriz[matriz["Rubro"] == "TOTAL GASTO"]
    if tg.empty:
        return pd.DataFrame({"Cuartel": vista, "Total": [0.0] * len(vista)})
    return pd.DataFrame(
        {
            "Cuartel": vista,
            "Total": [float(tg.iloc[0].get(c, 0) or 0) for c in vista],
        }
    )


def dataframe_gastos_dashboard_espino(demo: Any, conn, prorrateo_rrhh: dict) -> pd.DataFrame:
    """Totales por variedad — misma matriz que módulo Costos (histórico completo)."""
    nombre, fi, ff = demo._temporada_vigente_costos()
    matriz = armar_matriz_costos_espino(
        demo, conn, prorrateo_rrhh, nombre,
        None, None, fi_rrhh=fi, ff_rrhh=ff,
    )
    return totales_por_variedad_dataframe(matriz, demo)


def resumen_costos_para_flujo_espino(demo: Any, conn, temporada: str, fi, ff) -> dict:
    """Resumen costos para Flujo financiero Espino."""
    from erp_flujo_financiero import resumen_desde_matriz_costos

    from demo_web.services.native._helpers import hoy_demo, prorrateo_rrhh

    prorr = prorrateo_rrhh(demo, conn)
    hoy = hoy_demo(demo)
    es_vigente = fi <= hoy <= ff
    resultado = armar_matriz_costos_espino_temporada(
        demo, conn, prorr, temporada, fi, ff, es_vigente,
    )
    return resumen_desde_matriz_costos(resultado.matriz, resultado.cuarteles_vista)


def verificar_parity_dashboard_costos(
    demo: Any,
    conn,
    prorrateo_rrhh: dict,
    *,
    tolerancia: float = 1.0,
) -> tuple[bool, str]:
    """Comprueba que Dashboard y matriz temporada Espino coinciden en total."""
    dfr = dataframe_gastos_dashboard_espino(demo, conn, prorrateo_rrhh)
    total_dash = float(dfr["Total"].sum())
    nombre, fi, ff = demo._temporada_vigente_costos()
    hoy = demo.hora_chile()
    if hasattr(hoy, "date"):
        hoy = hoy.date()
    fi_d = fi.date() if hasattr(fi, "date") else fi
    ff_d = ff.date() if hasattr(ff, "date") else ff
    es_vigente = fi_d <= hoy <= ff_d
    resultado = armar_matriz_costos_espino_temporada(
        demo, conn, prorrateo_rrhh, nombre, fi, ff, es_vigente,
    )
    total_costos = total_gasto_matriz_espino(resultado.matriz, demo)
    diff = abs(total_dash - total_costos)
    ok = diff <= tolerancia
    msg = f"Dashboard={total_dash:,.0f} Costos={total_costos:,.0f} diff={diff:,.2f}"
    return ok, msg


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
