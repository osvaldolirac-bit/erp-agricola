"""Guardas tenant Espino: duplicados GE, facturas, kardex bodega y estado Tesorería."""
from __future__ import annotations

import sqlite3

DOC_GE_PREFIX = "GE-"
MONTO_TOLERANCIA_GE = 500.0


def _espino() -> bool:
    try:
        from demo_web.services.tenant_scope import is_espino_tenant

        return is_espino_tenant()
    except Exception:
        return False


def _buscar_ge_duplicado(
    conn: sqlite3.Connection,
    nro_documento: str,
    fecha_compra: str,
    monto_total: float,
) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT id, nro_documento, proveedor, monto_total
        FROM facturas
        WHERE nro_documento GLOB 'GE-*'
          AND nro_documento NOT GLOB '*_P'
          AND TRIM(proveedor) = TRIM(?)
          AND fecha_compra = ?
          AND ABS(monto_total - ?) < ?
        LIMIT 1
        """,
        (str(nro_documento or "").strip(), str(fecha_compra or ""), float(monto_total or 0), MONTO_TOLERANCIA_GE),
    ).fetchone()


def consolidar_ge_duplicado_al_ingresar(
    conn: sqlite3.Connection,
    nro_documento: str,
    proveedor: str,
    fecha_compra: str,
    monto_total: float,
) -> str | None:
    """Migra imputaciones GE _P a la factura real y elimina el padre GE. Retorna GE nro si consolidó."""
    if not _espino():
        return None
    ge = _buscar_ge_duplicado(conn, nro_documento, fecha_compra, monto_total)
    if not ge:
        return None
    ge_id = int(ge["id"])
    ge_nro = str(ge["nro_documento"] or "")
    ge_prov = str(ge["proveedor"] or "")
    nro = str(nro_documento or "").strip()
    prov = str(proveedor or "").strip()
    conn.execute(
        """
        UPDATE facturas
        SET nro_documento = ?, proveedor = ?
        WHERE nro_documento = ? AND proveedor = ?
        """,
        (f"{nro}_P", prov, f"{ge_nro}_P", ge_prov),
    )
    conn.execute("DELETE FROM facturas WHERE id = ?", (ge_id,))
    return ge_nro


def validar_nueva_factura_compra(
    conn: sqlite3.Connection,
    nro_documento: str,
    proveedor: str,
    *,
    fecha_compra: str | None = None,
    monto_total: float | None = None,
    exclude_id: int = 0,
) -> tuple[bool, str]:
    """Evita duplicados de documento y bloquea ingreso GE-* manual."""
    nro = str(nro_documento or "").strip()
    prov = str(proveedor or "").strip()
    if not nro or not prov:
        return False, "Proveedor y N° documento son obligatorios."
    if nro.upper().startswith(DOC_GE_PREFIX):
        return False, (
            "Los documentos GE-* son imputaciones históricas de Costos. "
            "Ingrese el N° de factura real del proveedor."
        )
    dup = conn.execute(
        """
        SELECT id FROM facturas
        WHERE nro_documento = ?
          AND proveedor = ?
          AND nro_documento NOT GLOB '*_P'
          AND id != ?
        LIMIT 1
        """,
        (nro, prov, int(exclude_id or 0)),
    ).fetchone()
    if dup:
        return False, f"Ya existe la factura {nro} de {prov}."
    if _espino() and fecha_compra and monto_total is not None:
        ge = _buscar_ge_duplicado(conn, nro, fecha_compra, float(monto_total))
        if ge:
            return True, ""
    return True, ""


def validar_estado_pago_coherente(estado: str, monto_total: float, monto_pagado: float) -> tuple[bool, str]:
    """Pagado exige abono registrado (evita ocultar deuda en Tesorería)."""
    if str(estado or "").strip() == "Pagado":
        if float(monto_pagado or 0) < float(monto_total or 0) - 0.01:
            return False, (
                "No se puede marcar Pagado sin abono completo. "
                "Registre el pago en Tesorería o deje Pendiente."
            )
    return True, ""


def registrar_ingreso_kardex_compra_espino(
    demo,
    conn: sqlite3.Connection,
    producto_id: int,
    cantidad: float,
    precio_unitario: float,
    fecha: str,
) -> None:
    """Ingreso kardex bodega al comprar insumo (Espino): alimenta PMP para riego/LC."""
    if not _espino() or cantidad <= 0:
        return
    from demo_web.services.native import espino_bodega

    um_row = conn.execute(
        "SELECT COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, int(producto_id)),
    ).fetchone()
    um = um_row[0] if um_row else demo.DEFAULT_UNIDAD_INSUMO
    valor = round(float(cantidad) * float(precio_unitario or 0), 2)
    conn.execute(
        """
        INSERT INTO movimientos
        (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
        VALUES (?, 'Ingreso', ?, ?, ?, ?, ?)
        """,
        (int(producto_id), float(cantidad), str(fecha), espino_bodega.CC_ESPINO, valor, um),
    )
    espino_bodega._sync_inventario_stock(conn, int(producto_id))
    pmp_k = espino_bodega._precio_medio_kardex(conn, int(producto_id))
    if pmp_k is not None:
        conn.execute(
            "UPDATE inventario SET precio_medio = ? WHERE id = ?",
            (round(pmp_k, 4), int(producto_id)),
        )
