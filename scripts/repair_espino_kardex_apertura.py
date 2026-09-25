#!/usr/bin/env python3
"""Backfill ingresos de apertura kardex para productos con stock pero sin movimientos."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path("/root/espino/erp_espino.db")
CC = "Cerezos"
FECHA_APERTURA = "2026-09-01"


def main() -> int:
    if not DB.is_file():
        print(f"ERROR: no existe {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT i.id, i.producto, i.stock, i.precio_medio,
               COALESCE(i.unidad_medida, 'kg') AS um,
               COALESCE((
                   SELECT SUM(cantidad) FROM movimientos m
                   WHERE m.producto_id = i.id AND m.tipo = 'Ingreso'
                     AND UPPER(TRIM(m.centro_costo)) IN ('CEREZOS', 'EL ESPINO')
               ), 0) AS ing_kardex
        FROM inventario i
        WHERE COALESCE(i.stock, 0) > 0
        ORDER BY i.producto
        """
    ).fetchall()
    n = 0
    for r in rows:
        if float(r["ing_kardex"] or 0) > 1e-9:
            continue
        stock = float(r["stock"])
        pmp = float(r["precio_medio"] or 0)
        if pmp <= 0:
            print(f"  SKIP {r['producto']}: sin PMP")
            continue
        valor = round(stock * pmp, 2)
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?, 'Ingreso', ?, ?, ?, ?, ?)""",
            (int(r["id"]), stock, FECHA_APERTURA, CC, valor, r["um"]),
        )
        n += 1
        print(f"  + {r['producto']}: apertura {stock} {r['um']} (${valor:,.0f})")
    conn.commit()
    conn.close()
    print(f"Listo — {n} apertura(s) creada(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
