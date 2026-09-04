"""Excluir razón social El Espino del tenant LC (Compras, Tesorería, Costos, Dashboard)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from demo_web.services.tenant_scope import RAZON_SOCIAL_ESPINO, is_concepcion_tenant

CUARTEL_ESPINO_LC = "EL ESPINO"


def excluir_razon_social_espino_en_lc() -> bool:
    return is_concepcion_tenant()


def es_razon_social_espino_excluida(razon: str | None) -> bool:
    return (razon or "").strip().casefold() == RAZON_SOCIAL_ESPINO.casefold()


def sql_and_excluir_razon_social_espino(col: str = "razon_social", alias: str | None = None) -> str:
    """Fragmento AND para queries SQL (solo tenant LC)."""
    if not excluir_razon_social_espino_en_lc():
        return ""
    col_ref = f"{alias}.{col}" if alias else col
    return f" AND TRIM(COALESCE({col_ref}, '')) != '{RAZON_SOCIAL_ESPINO}' "


def cuarteles_costos_lc(cuarteles: list[str] | None) -> list[str]:
    """Quita cuartel EL ESPINO de vistas Costos/Flujo en tenant LC."""
    if not excluir_razon_social_espino_en_lc() or not cuarteles:
        return list(cuarteles or [])
    return [c for c in cuarteles if str(c).upper().strip() != CUARTEL_ESPINO_LC]


def ocultar_cuartel_espino_en_matriz_lc(matriz: pd.DataFrame | None) -> pd.DataFrame | None:
    """Anula gastos del cuartel EL ESPINO en matriz Costos (solo LC)."""
    if not excluir_razon_social_espino_en_lc() or matriz is None or matriz.empty:
        return matriz
    if CUARTEL_ESPINO_LC not in matriz.columns:
        return matriz
    cierre = {"TOTAL GASTO", "PRESUPUESTO", "SALDO"}
    body = matriz[~matriz["Rubro"].isin(cierre)].copy()
    body[CUARTEL_ESPINO_LC] = 0.0
    if "TOTAL" in body.columns:
        skip = {"Rubro", "TOTAL", "% Total"}
        cc_cols = [c for c in body.columns if c not in skip]
        body["TOTAL"] = body[cc_cols].sum(axis=1)
    ppto = matriz[matriz["Rubro"] == "PRESUPUESTO"]
    if not ppto.empty:
        body = pd.concat([body, ppto], ignore_index=True)
    return _recomputar_cierre_matriz(body)


def resumen_costos_para_flujo_lc(conn, demo: Any, temporada: str, fi, ff) -> dict:
    """Misma matriz que Costos con exclusiones LC (razón social + cuartel Espino)."""
    from erp_flujo_financiero import resumen_desde_matriz_costos

    from demo_web.services.native._helpers import hoy_demo, prorrateo_rrhh
    from demo_web.services.tenant_scope import cuarteles_oficiales

    cuarteles_full = list(cuarteles_oficiales(demo) or [])
    cuarteles = cuarteles_costos_lc(cuarteles_full)
    hoy = hoy_demo(demo)
    prorr = prorrateo_rrhh(demo, conn)
    es_vigente = fi <= hoy <= ff
    fi_cons, ff_cons = demo._rango_fechas_costos_consulta(conn, fi, ff, es_vigente)
    if es_vigente:
        matriz = demo._armar_matriz_costos_vista_b(
            conn, fi_cons, ff_cons, cuarteles_full, prorr, temporada,
            fi_rrhh=fi, ff_rrhh=ff,
        )
        det_fi, det_ff = fi_cons, ff_cons
    else:
        matriz = demo._armar_matriz_costos_vista_b(
            conn, fi, ff, cuarteles_full, prorr, temporada,
        )
        det_fi, det_ff = fi, ff
    matriz = ajustar_matriz_costos_excluir_espino_lc(
        conn, demo, matriz, cuarteles_full, det_fi, det_ff,
    )
    matriz = ocultar_cuartel_espino_en_matriz_lc(matriz)
    return resumen_desde_matriz_costos(matriz, cuarteles)


def filtrar_df_facturas_espino_lc(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if not excluir_razon_social_espino_en_lc() or df is None or df.empty:
        return df
    if "razon_social" not in df.columns:
        return df
    mask = ~df["razon_social"].astype(str).str.strip().map(es_razon_social_espino_excluida)
    return df.loc[mask].copy()


def _nros_imputacion_espino_lc(conn) -> set[str]:
    if not excluir_razon_social_espino_en_lc():
        return set()
    rows = conn.execute(
        """SELECT p.nro_documento
           FROM facturas p
           INNER JOIN facturas f
             ON f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento) - 2)
            AND f.proveedor = p.proveedor
           WHERE p.nro_documento LIKE '%_P'
             AND TRIM(COALESCE(f.razon_social, '')) = ?""",
        (RAZON_SOCIAL_ESPINO,),
    ).fetchall()
    return {str(r[0]) for r in rows}


def filtrar_detalle_movimientos_espino_lc(conn, df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Quita líneas de costos imputadas desde facturas razón social El Espino."""
    if df is None or df.empty or not excluir_razon_social_espino_en_lc():
        return df
    excluidos = _nros_imputacion_espino_lc(conn)
    if not excluidos:
        return df

    def _mantener(row) -> bool:
        det = str(row.get("Detalle") or "")
        for nro_p in excluidos:
            base = nro_p[:-2] if nro_p.endswith("_P") else nro_p
            if base and base in det:
                return False
        return True

    out = df[df.apply(_mantener, axis=1)].copy()
    return out.reset_index(drop=True)


def _recomputar_cierre_matriz(matriz: pd.DataFrame) -> pd.DataFrame:
    cierre = {"TOTAL GASTO", "PRESUPUESTO", "SALDO"}
    body = matriz[~matriz["Rubro"].isin(cierre)].copy()
    cols = [c for c in body.columns if c != "Rubro"]
    total_gasto = {c: float(body[c].sum()) for c in cols}
    ppto_row = matriz[matriz["Rubro"] == "PRESUPUESTO"]
    if not ppto_row.empty:
        ppto = {c: float(ppto_row.iloc[0].get(c) or 0) for c in cols}
    else:
        ppto = {c: 0.0 for c in cols}
    saldo = {c: ppto[c] - total_gasto[c] for c in cols}
    footer = pd.DataFrame(
        [
            {"Rubro": "TOTAL GASTO", **total_gasto},
            {"Rubro": "PRESUPUESTO", **ppto},
            {"Rubro": "SALDO", **saldo},
        ]
    )
    return pd.concat([body, footer], ignore_index=True)


def ajustar_matriz_costos_excluir_espino_lc(
    conn,
    demo: Any,
    matriz: pd.DataFrame | None,
    cuarteles: list[str],
    fi=None,
    ff=None,
) -> pd.DataFrame | None:
    """Resta imputaciones _P de facturas El Espino y recalcula totales (solo LC)."""
    if not excluir_razon_social_espino_en_lc() or matriz is None or matriz.empty:
        return matriz

    filtro_f = ""
    params: list[Any] = [getattr(demo, "TIPO_GASTO_SIN_CLASIFICAR", "Sin clasificar")]
    if fi and ff:
        filtro_f = " AND f.fecha_compra BETWEEN ? AND ? "
        params.extend([str(fi), str(ff)])

    params.append(RAZON_SOCIAL_ESPINO)
    q = f"""
        SELECT p.nro_documento, p.proveedor,
               UPPER(TRIM(p.centro_costo)) AS cc,
               COALESCE(NULLIF(TRIM(p.tipo_gasto), ''), ?) AS tg,
               COALESCE(p.monto_imputado, 0) AS m
        FROM facturas p
        INNER JOIN facturas f
          ON f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento) - 2)
         AND f.proveedor = p.proveedor
        WHERE p.nro_documento LIKE '%_P'
          AND p.nro_documento NOT LIKE '%_RRHH'
          AND TRIM(COALESCE(f.razon_social, '')) = ?
          AND ABS(COALESCE(p.monto_imputado, 0)) > 0.01
          {filtro_f}
    """
    rows = conn.execute(q, params).fetchall()
    if not rows:
        return matriz

    factores = {}
    fn_fact = getattr(demo, "_factores_monto_bruto_facturas", None)
    if callable(fn_fact):
        try:
            factores = fn_fact(conn, fi, ff) or {}
        except Exception:
            factores = {}

    fn_monto = getattr(demo, "_monto_costos_factura_imputada", None)
    fn_rubro = getattr(demo, "_rubro_valido_matriz", None)
    if not callable(fn_rubro):
        fn_rubro = getattr(demo, "_rubro_matriz_desde_tipo_gasto", None)

    cc_canon = {str(c).upper().strip(): c for c in cuarteles}
    cierre = {"TOTAL GASTO", "PRESUPUESTO", "SALDO"}
    out = matriz[~matriz["Rubro"].isin(cierre)].copy()

    for nro_p, prov, cc_raw, tg, m_raw in rows:
        cc_key = cc_canon.get(str(cc_raw or "").upper().strip())
        if not cc_key or cc_key not in out.columns:
            continue
        monto = float(m_raw or 0)
        if callable(fn_monto) and factores is not None:
            try:
                monto = float(fn_monto(factores, nro_p, prov, monto) or 0)
            except Exception:
                pass
        rubro = None
        if callable(fn_rubro):
            try:
                rubro = fn_rubro(tg)
            except Exception:
                rubro = None
        if not rubro:
            continue
        fn_neto = getattr(demo, "_monto_costos_factura_matriz", None)
        if callable(fn_neto):
            try:
                monto = float(fn_neto(rubro, monto, neto_facturas_iva=True) or 0)
            except TypeError:
                try:
                    monto = float(fn_neto(rubro, monto) or 0)
                except Exception:
                    pass
            except Exception:
                pass
        mask = out["Rubro"] == rubro
        if not mask.any():
            continue
        idx = out.index[mask][0]
        out.at[idx, cc_key] = max(0.0, float(out.at[idx, cc_key] or 0) - monto)
        if "TOTAL" in out.columns:
            out.at[idx, "TOTAL"] = max(0.0, float(out.at[idx, "TOTAL"] or 0) - monto)

    ppto = matriz[matriz["Rubro"] == "PRESUPUESTO"]
    if not ppto.empty:
        out = pd.concat([out, ppto], ignore_index=True)
    return _recomputar_cierre_matriz(out)


def ajustar_gastos_dashboard_excluir_espino_lc(
    conn,
    demo: Any,
    dfr_base: pd.DataFrame | None,
    cuarteles: list[str],
) -> pd.DataFrame | None:
    """Resta gastos El Espino del panel dashboard por cuartel."""
    if not excluir_razon_social_espino_en_lc() or dfr_base is None or dfr_base.empty:
        return dfr_base

    q = """
        SELECT UPPER(TRIM(p.centro_costo)) AS cc, SUM(COALESCE(p.monto_imputado, 0)) AS m
        FROM facturas p
        INNER JOIN facturas f
          ON f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento) - 2)
         AND f.proveedor = p.proveedor
        WHERE p.nro_documento LIKE '%_P'
          AND TRIM(COALESCE(f.razon_social, '')) = ?
          AND ABS(COALESCE(p.monto_imputado, 0)) > 0.01
        GROUP BY 1
    """
    rows = conn.execute(q, (RAZON_SOCIAL_ESPINO,)).fetchall()
    if not rows:
        return dfr_base

    cc_canon = {str(c).upper().strip(): c for c in cuarteles}
    out = dfr_base.copy()
    resta_total = 0.0
    for cc_raw, m in rows:
        cc_key = cc_canon.get(str(cc_raw or "").upper().strip())
        if not cc_key:
            continue
        monto = float(m or 0)
        resta_total += monto
        mask = out["Cuartel"].astype(str) == cc_key
        if mask.any():
            out.loc[mask, "Total"] = out.loc[mask, "Total"].apply(
                lambda v: max(0.0, float(v or 0) - monto)
            )
    mask_tg = out["Cuartel"].astype(str).str.upper() == "TOTAL GENERAL"
    if mask_tg.any() and resta_total > 0:
        out.loc[mask_tg, "Total"] = out.loc[mask_tg, "Total"].apply(
            lambda v: max(0.0, float(v or 0) - resta_total)
        )
    return out
