"""Coherencia Compras (registrado bruto) vs Costos (imputación desde facturas)."""
from __future__ import annotations

from typing import Any, Iterator

from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino

DOC_IMPUTACION_COSTOS_PREFIX = "GE-"


def sql_historial_compras_parent(col_prefix: str = "") -> str:
    """Parent en historial Compras: incluye INT-, excluye _P y GE-*."""
    p = f"{col_prefix}." if col_prefix else ""
    return f"""
          AND {p}nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'GE-*'
    """


def sql_join_parent_imputacion(alias_p: str = "p", alias_f: str = "f") -> str:
    return f"""
        INNER JOIN facturas {alias_f}
          ON {alias_f}.nro_documento = SUBSTR({alias_p}.nro_documento, 1, LENGTH({alias_p}.nro_documento) - 2)
         AND {alias_f}.proveedor = {alias_p}.proveedor
    """


def sql_filtro_imputacion_en_historial(alias_p: str = "p", alias_f: str = "f") -> str:
    """Solo imputaciones _P cuyo documento padre está en historial Compras."""
    return f"""
          AND {alias_p}.nro_documento LIKE '%_P'
          AND {alias_p}.nro_documento NOT LIKE '%_RRHH'
          AND ABS(COALESCE({alias_p}.monto_imputado, 0)) > 0.01
          AND {alias_f}.monto_total > 0
          {sql_historial_compras_parent(alias_f)}
          {sql_and_excluir_razon_social_espino('razon_social', alias_f)}
    """


def total_registrado_compras_historial(conn, fi, ff) -> float:
    sql = f"""
        SELECT COALESCE(SUM(f.monto_total), 0)
        FROM facturas f
        WHERE f.monto_total > 0
          {sql_historial_compras_parent('f')}
          AND f.fecha_compra BETWEEN ? AND ?
          {sql_and_excluir_razon_social_espino('razon_social', 'f')}
    """
    return float(conn.execute(sql, (str(fi), str(ff))).fetchone()[0] or 0)


def _iter_imputaciones_historial(conn, demo: Any, fi, ff) -> Iterator[tuple]:
    tg_default = getattr(demo, "TIPO_GASTO_SIN_CLASIFICAR", "Sin clasificar")
    sql = f"""
        SELECT p.nro_documento, p.proveedor, p.monto_imputado,
               COALESCE(NULLIF(TRIM(p.tipo_gasto), ''), ?) AS tg
        FROM facturas p
        {sql_join_parent_imputacion('p', 'f')}
        WHERE 1=1
          {sql_filtro_imputacion_en_historial('p', 'f')}
          AND f.fecha_compra BETWEEN ? AND ?
    """
    return conn.execute(sql, (tg_default, str(fi), str(ff))).fetchall()


def _escala_imputacion(demo: Any, conn, fi, ff, nro_p, prov, monto_raw) -> float:
    monto = float(monto_raw or 0)
    fn_fact = getattr(demo, "_factores_monto_bruto_facturas", None)
    fn_imp = getattr(demo, "_monto_costos_factura_imputada", None)
    factores = {}
    if callable(fn_fact):
        try:
            factores = fn_fact(conn, fi, ff) or {}
        except Exception:
            factores = {}
    if callable(fn_imp):
        try:
            monto = float(fn_imp(factores, nro_p, prov, monto) or 0)
        except Exception:
            pass
    return monto


def total_imputado_bruto_historial(demo: Any, conn, fi, ff) -> float:
    """Imputaciones _P en bruto (misma escala que monto_total del historial)."""
    fn_neto = getattr(demo, "_monto_costos_factura_matriz", None)
    total = 0.0
    for nro_p, prov, m_raw, _tg in _iter_imputaciones_historial(conn, demo, fi, ff):
        monto = _escala_imputacion(demo, conn, fi, ff, nro_p, prov, m_raw)
        if callable(fn_neto):
            try:
                monto = float(fn_neto("", monto, neto_facturas_iva=False) or 0)
            except TypeError:
                pass
            except Exception:
                pass
        total += monto
    return total


def total_imputado_neto_historial(demo: Any, conn, fi, ff) -> float:
    """Imputaciones _P en neto (criterio Costos: ÷1.19 en rubros con IVA)."""
    fn_rubro = getattr(demo, "_rubro_valido_matriz", None) or getattr(
        demo, "_rubro_matriz_desde_tipo_gasto", None
    )
    fn_neto = getattr(demo, "_monto_costos_factura_matriz", None)
    total = 0.0
    for nro_p, prov, m_raw, tg in _iter_imputaciones_historial(conn, demo, fi, ff):
        monto = _escala_imputacion(demo, conn, fi, ff, nro_p, prov, m_raw)
        rubro = None
        if callable(fn_rubro):
            try:
                rubro = fn_rubro(tg)
            except Exception:
                rubro = None
        if callable(fn_neto) and rubro:
            try:
                monto = float(fn_neto(rubro, monto, neto_facturas_iva=True) or 0)
            except TypeError:
                try:
                    monto = float(fn_neto(rubro, monto) or 0)
                except Exception:
                    pass
            except Exception:
                pass
        total += monto
    return total
