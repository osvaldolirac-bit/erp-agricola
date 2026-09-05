"""Filtros CxP Tesorería alineados con erp_flujo_financiero._cargar_tesoreria."""


def sql_solo_cxp_tesoreria(col_prefix: str = "") -> str:
    """Deuda real: excluye imputaciones _P y GE-*. INT- solo fuera de Espino."""
    p = f"{col_prefix}." if col_prefix else ""
    excl_int = ""
    try:
        from demo_web.services.tenant_scope import is_espino_tenant

        if not is_espino_tenant():
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
        from demo_web.services.tenant_scope import is_espino_tenant

        return not is_espino_tenant()
    except Exception:
        return True


def saldo_factura_tesoreria(monto_total, monto_pagado, imputado_costos=0) -> float:
    bruto = max(0.0, float(monto_total or 0) - float(monto_pagado or 0))
    if usar_saldo_cxp_neto_en_tesoreria():
        return saldo_cxp_neto(monto_total, monto_pagado, imputado_costos)
    return bruto
