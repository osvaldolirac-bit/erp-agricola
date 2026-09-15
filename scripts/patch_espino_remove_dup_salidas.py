#!/usr/bin/env python3
"""Elimina salidas bodega bulk duplicadas (apps LC 1–2, era Cerezos).

En las primeras aplicaciones LC se registró una salida total del evento
Y además una salida por producto → el kardex restaba el doble.

IDs conocidos en erp_espino.db (ago 2026):
  4  ACEITE BIOIL SPRAY  210 L
  5  COBRE NORDOX         18.9
  7  PIRIPROXIFEN          7.0

Uso: python3 scripts/patch_espino_remove_dup_salidas.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DUP_SALIDA_IDS = (4, 5, 7)


def plan(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    for mid in DUP_SALIDA_IDS:
        row = conn.execute(
            """SELECT m.id, i.producto, m.cantidad, m.fecha, m.tipo
               FROM movimientos m JOIN inventario i ON i.id=m.producto_id
               WHERE m.id=?""",
            (mid,),
        ).fetchone()
        if row:
            lines.append(f"DELETE id={row[0]} · {row[1]} −{row[2]} · {row[3]} ({row[4]})")
        else:
            lines.append(f"SKIP id={mid} (no existe)")
    return lines


def apply(conn: sqlite3.Connection) -> None:
    for mid in DUP_SALIDA_IDS:
        conn.execute("DELETE FROM movimientos WHERE id=? AND tipo='Salida'", (mid,))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")
    conn = sqlite3.connect(str(db))
    try:
        print("=== Salidas bulk duplicadas ===")
        for line in plan(conn):
            print(line)
        if do_apply:
            apply(conn)
            conn.commit()
            print("=== Aplicado — ejecute patch_espino_sync_inventario_stock.py --apply ===")
        else:
            print("=== Dry-run ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
