"""Filtros CxP Tesorería alineados con erp_flujo_financiero._cargar_tesoreria."""


def sql_solo_cxp_tesoreria(col_prefix: str = "") -> str:
    """Deuda real: excluye imputaciones _P, GE-* e INT- (internos / Compras sin factura)."""
    p = f"{col_prefix}." if col_prefix else ""
    return f"""
          AND {p}nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'GE-*'
          AND UPPER(TRIM({p}nro_documento)) NOT GLOB 'INT-*'
    """
