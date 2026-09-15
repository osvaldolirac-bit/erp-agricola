#!/usr/bin/env python3
"""Corrige fecha Libro de Campo apps 6 y 7 El Espino → 2026-09-13.

Sincroniza salidas bodega vinculadas (mismos productos/cantidades).

Uso: python3 scripts/patch_espino_lc_fecha_app_6_7.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

NUEVA_FECHA = "2026-09-13"
APPS = (6, 7)
# Salidas bodega pareadas (ids conocidos Espino sep-2026).
MOV_SALIDA_IDS = (25, 26, 27, 28, 29, 35, 36, 37, 38, 39)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    conn = sqlite3.connect(str(db))
    try:
        lc = conn.execute(
            """SELECT id, n_aplicacion, fecha, sector, producto
               FROM libro_campo WHERE CAST(n_aplicacion AS INTEGER) IN (?,?)
               ORDER BY n_aplicacion, id""",
            APPS,
        ).fetchall()
        mov = conn.execute(
            f"""SELECT m.id, m.fecha, m.centro_costo, i.producto, m.cantidad
                FROM movimientos m JOIN inventario i ON i.id=m.producto_id
                WHERE m.id IN ({",".join("?" * len(MOV_SALIDA_IDS))})
                ORDER BY m.id""",
            MOV_SALIDA_IDS,
        ).fetchall()
        print(f"=== LC apps {APPS} → {NUEVA_FECHA} ({len(lc)} filas) ===")
        for r in lc:
            print(f"  id={r[0]} app={r[1]} {r[2]} {r[3]} {r[4]}")
        print(f"=== Movimientos bodega ({len(mov)} filas) ===")
        for r in mov:
            print(f"  id={r[0]} {r[1]} {r[2]} {r[3]} {r[4]}")
        if do_apply:
            conn.execute(
                """UPDATE libro_campo SET fecha=?
                   WHERE CAST(n_aplicacion AS INTEGER) IN (?,?)""",
                (NUEVA_FECHA, *APPS),
            )
            conn.execute(
                f"""UPDATE movimientos SET fecha=?
                    WHERE id IN ({",".join("?" * len(MOV_SALIDA_IDS))})""",
                (NUEVA_FECHA, *MOV_SALIDA_IDS),
            )
            conn.commit()
            print("OK — fechas actualizadas.")
        else:
            print("=== Dry-run (--apply para ejecutar) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
