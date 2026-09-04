"""Filtros CxP Tesorería alineados con erp_flujo_financiero._cargar_tesoreria."""


def sql_solo_cxp_tesoreria(col_prefix: str = "") -> str:
    """Deuda real: excluye imputaciones _P, GE-* e INT- (internos / Compras sin factura)."""
    p = f"{col_prefix}." if col_prefix else ""
    return f"""
          AND {p}nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'GE-*'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'INT-*'
    """


def sql_imputado_costos_subquery(alias_f: str = "f") -> str:
    """Suma imputaciones _P del documento (evita doble conteo vs Costos)."""
    return f"""
        COALESCE((
            SELECT SUM(ABS(p.monto_imputado))
            FROM facturas p
            WHERE p.nro_documento = {alias_f}.nro_documento || '_P'
              AND p.proveedor = {alias_f}.proveedor
              AND ABS(COALESCE(p.monto_imputado, 0)) > 0.01
        ), 0)
    """


def saldo_cxp_neto(monto_total, monto_pagado, imputado_costos) -> float:
    """Saldo CxP neto = bruto − abonos − lo ya imputado a Costos."""
    bruto = max(0.0, float(monto_total or 0) - float(monto_pagado or 0))
    imp = max(0.0, float(imputado_costos or 0))
    return max(0.0, bruto - min(bruto, imp))
