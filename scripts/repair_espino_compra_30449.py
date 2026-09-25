#!/usr/bin/env python3
"""Backfill kardex bodega para factura TOPAGRO 30449 (2026-09-23) tenant El Espino."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path("/root/espino/erp_espino.db")
FACTURA_ID = 1071
FECHA = "2026-09-23"
CC_INGRESO = "Cerezos"

# Precios unitarios netos al momento de la compra (desde inventario.precio_medio post-compra).
REPAIR_ITEMS = (
    {"producto_id": 109, "cantidad": 1.0, "precio_unit": 113234.7976, "um": "kg"},
    {"producto_id": 117, "cantidad": 20.0, "precio_unit": 3026.78, "um": "lt"},
    {"producto_id": 118, "cantidad": 15.0, "precio_unit": 3310.54, "um": "lt"},
)


def _ingresos_pool(conn: sqlite3.Connection, producto_id: int) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
           WHERE producto_id=? AND tipo='Ingreso'
             AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')""",
        (producto_id,),
    ).fetchone()
    return float(row[0] or 0)


def _ya_tiene_ingreso(conn: sqlite3.Connection, producto_id: int, cantidad: float) -> bool:
    row = conn.execute(
        """SELECT 1 FROM movimientos
           WHERE producto_id=? AND tipo='Ingreso' AND fecha=? AND ABS(cantidad - ?) < 1e-4
             AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')
           LIMIT 1""",
        (producto_id, FECHA, cantidad),
    ).fetchone()
    return row is not None


def _sync_stock(conn: sqlite3.Connection, producto_id: int) -> float:
    ing = _ingresos_pool(conn, producto_id)
    if ing <= 1e-9:
        row = conn.execute("SELECT COALESCE(stock,0) FROM inventario WHERE id=?", (producto_id,)).fetchone()
        return float(row[0] or 0)
    sal_row = conn.execute(
        "SELECT COALESCE(SUM(cantidad),0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
        (producto_id,),
    ).fetchone()
    sal = float(sal_row[0] or 0)
    stock = max(ing - sal, 0.0)
    conn.execute("UPDATE inventario SET stock=? WHERE id=?", (stock, producto_id))
    return stock


def _sync_pmp(conn: sqlite3.Connection, producto_id: int) -> None:
    row = conn.execute(
        """SELECT COALESCE(SUM(valor_imputado),0), COALESCE(SUM(cantidad),0)
           FROM movimientos
           WHERE producto_id=? AND tipo='Ingreso'
             AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')""",
        (producto_id,),
    ).fetchone()
    if row and float(row[1] or 0) > 1e-9:
        pmp = float(row[0]) / float(row[1])
        conn.execute(
            "UPDATE inventario SET precio_medio=? WHERE id=?",
            (round(pmp, 4), producto_id),
        )


def main() -> int:
    if not DB.is_file():
        print(f"ERROR: no existe {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    fac = conn.execute(
        "SELECT id, nro_documento, proveedor, fecha_compra FROM facturas WHERE id=?",
        (FACTURA_ID,),
    ).fetchone()
    if not fac:
        print(f"ERROR: factura id {FACTURA_ID} no encontrada", file=sys.stderr)
        return 1
    print(f"Reparando factura {fac['nro_documento']} ({fac['proveedor']}) del {fac['fecha_compra']}")

    inserted = 0
    for item in REPAIR_ITEMS:
        pid = int(item["producto_id"])
        cant = float(item["cantidad"])
        prod = conn.execute("SELECT producto FROM inventario WHERE id=?", (pid,)).fetchone()
        if not prod:
            print(f"  SKIP id {pid}: producto no existe")
            continue
        if _ya_tiene_ingreso(conn, pid, cant):
            print(f"  OK {prod['producto']}: ingreso {cant} ya existe en {FECHA}")
            continue
        valor = round(cant * float(item["precio_unit"]), 2)
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?, 'Ingreso', ?, ?, ?, ?, ?)""",
            (pid, cant, FECHA, CC_INGRESO, valor, item["um"]),
        )
        inserted += 1
        stock = _sync_stock(conn, pid)
        _sync_pmp(conn, pid)
        print(f"  + {prod['producto']}: ingreso {cant} {item['um']} (${valor:,.0f}) → stock {stock}")

    conn.commit()
    conn.close()
    print(f"Listo — {inserted} movimiento(s) insertado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
