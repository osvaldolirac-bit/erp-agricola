"""LC: Costos registra el neto aunque la factura se haya ingresado por el bruto.

Repuestos, energía y agroquímicos se muestran neto (÷ 1,19). La marca
costo_respeta_bruto queda en la base por documentos antiguos y ya no cambia
el monto del centro de costo. El petróleo sigue su neto propio: bruto ÷ 1,19
menos el impuesto específico por litro, en el módulo de petróleo.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def ensure_costo_respeta_bruto(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(facturas)")}
    if "costo_respeta_bruto" in cols:
        return
    conn.execute(
        "ALTER TABLE facturas ADD COLUMN costo_respeta_bruto INTEGER NOT NULL DEFAULT 0"
    )


def marcar_imputacion_respeta_bruto(
    conn: sqlite3.Connection,
    nro: str,
    proveedor: str,
    respeta: bool,
) -> None:
    """Deja la marca histórica en el documento. Costos ya no la usa para el monto."""
    ensure_costo_respeta_bruto(conn)
    flag = 1 if respeta else 0
    conn.execute(
        """UPDATE facturas
           SET costo_respeta_bruto=?
           WHERE proveedor=? AND (nro_documento=? OR nro_documento=?)""",
        (flag, proveedor, nro, f"{nro}_P"),
    )


def claves_imputacion_bruta(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Documentos marcados en su momento. Costos no los excluye del neto."""
    try:
        ensure_costo_respeta_bruto(conn)
    except sqlite3.OperationalError:
        return set()
    rows = conn.execute(
        """SELECT p.nro_documento, p.proveedor
           FROM facturas p
           INNER JOIN facturas f
             ON f.nro_documento = SUBSTR(p.nro_documento, 1, LENGTH(p.nro_documento) - 2)
            AND f.proveedor = p.proveedor
           WHERE p.nro_documento LIKE '%_P'
             AND COALESCE(f.costo_respeta_bruto, 0) = 1"""
    ).fetchall()
    return {(str(nro or ""), str(prov or "")) for nro, prov in rows}


def instalar_imputacion_bruta_lc(erp: Any) -> None:
    """No altera el neto de Costos.

    El módulo compartido ya pasa a neto los rubros con IVA. Una versión anterior
    devolvía el bruto cuando el documento estaba marcado, y Ciruelos volvía a
    mostrar el total con IVA. Esa excepción queda fuera.
    """
    if getattr(erp, "_imputacion_bruta_lc", False):
        return
    if not all(
        callable(getattr(erp, name, None))
        for name in (
            "_factores_monto_bruto_facturas",
            "_monto_costos_factura_imputada",
            "_monto_costos_factura_matriz",
        )
    ):
        return
    erp._imputacion_bruta_lc = True
