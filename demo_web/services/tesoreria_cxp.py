"""Filtros CxP Tesorería alineados con erp_flujo_financiero._cargar_tesoreria."""


def sql_solo_cxp_tesoreria(col_prefix: str = "") -> str:
    """Deuda real: excluye imputaciones _P y GE-*. INT- según tenant_rules."""
    p = f"{col_prefix}." if col_prefix else ""
    excl_int = ""
    try:
        from demo_web.services.tenant_rules import cxp_incluye_documentos_int

        if not cxp_incluye_documentos_int():
            excl_int = f"\n          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'INT-*'"
    except Exception:
        excl_int = f"\n          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'INT-*'"
    return f"""
          AND {p}nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'GE-*'
          {excl_int}
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


def usar_saldo_cxp_neto_en_tesoreria() -> bool:
    """LC alinea CxP con Costos; Espino muestra deuda hasta el pago en Tesorería."""
    try:
        from demo_web.services.tenant_rules import cxp_usar_saldo_neto

        return cxp_usar_saldo_neto()
    except Exception:
        return True


def saldo_bruto_factura(monto_total, monto_pagado) -> float:
    """Saldo por pagar al proveedor (documento − abonos)."""
    return max(0.0, float(monto_total or 0) - float(monto_pagado or 0))


def saldo_factura_tesoreria(monto_total, monto_pagado, imputado_costos=0) -> float:
    """Saldo CxP neto para Flujo/resúmenes (LC descuenta imputación Costos)."""
    bruto = saldo_bruto_factura(monto_total, monto_pagado)
    if usar_saldo_cxp_neto_en_tesoreria():
        return saldo_cxp_neto(monto_total, monto_pagado, imputado_costos)
    return bruto


def saldo_factura_para_pago(monto_total, monto_pagado, imputado_costos=0) -> float:
    """Cola de pago Tesorería: imputar a Costos no sustituye el pago al proveedor."""
    return saldo_bruto_factura(monto_total, monto_pagado)
