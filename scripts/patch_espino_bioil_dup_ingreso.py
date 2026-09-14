#!/usr/bin/env python3
"""Elimina ingreso kardex duplicado ACEITE BIOIL SPRAY (210 L repetido).

Factura agrupa 210 L Bioil; había dos mov. Ingreso de 210 → stock fantasma 210.

Uso: python3 scripts/patch_espino_bioil_dup_ingreso.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DUP_INGRESO_ID = 8
PRODUCTO = "ACEITE BIOIL SPRAY"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            """SELECT m.id, i.producto, m.cantidad, m.fecha, m.tipo
               FROM movimientos m JOIN inventario i ON i.id=m.producto_id
               WHERE m.id=?""",
            (DUP_INGRESO_ID,),
        ).fetchone()
        pid = conn.execute("SELECT id FROM inventario WHERE producto=?", (PRODUCTO,)).fetchone()
        if not pid:
            raise SystemExit(f"Producto no encontrado: {PRODUCTO}")
        pid = int(pid[0])
        ing = float(
            conn.execute(
                """SELECT COALESCE(SUM(cantidad),0) FROM movimientos
                   WHERE producto_id=? AND tipo='Ingreso'
                   AND UPPER(centro_costo) IN ('CEREZOS','EL ESPINO')""",
                (pid,),
            ).fetchone()[0]
        )
        sal = float(
            conn.execute(
                "SELECT COALESCE(SUM(cantidad),0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
                (pid,),
            ).fetchone()[0]
        )
        inv = float(conn.execute("SELECT COALESCE(stock,0) FROM inventario WHERE id=?", (pid,)).fetchone()[0])
        nuevo = max(ing - sal, 0.0) if not do_apply else max(
            (ing - float(row[2] if row else 0)) - sal, 0.0
        )
        print(f"Actual: ing={ing} sal={sal} inv={inv}")
        if row:
            print(f"DELETE ingreso id={row[0]} {row[1]} +{row[2]} {row[3]}")
        print(f"Stock esperado tras fix: {max(ing - (float(row[2]) if row and do_apply else 0) - sal, 0):.2f} → sync {nuevo:.2f}")
        if do_apply and row:
            conn.execute("DELETE FROM movimientos WHERE id=? AND tipo='Ingreso'", (DUP_INGRESO_ID,))
            ing2 = float(
                conn.execute(
                    """SELECT COALESCE(SUM(cantidad),0) FROM movimientos
                       WHERE producto_id=? AND tipo='Ingreso'
                       AND UPPER(centro_costo) IN ('CEREZOS','EL ESPINO')""",
                    (pid,),
                ).fetchone()[0]
            )
            nuevo = max(ing2 - sal, 0.0)
            conn.execute("UPDATE inventario SET stock=? WHERE id=?", (nuevo, pid))
            conn.commit()
            print(f"OK — stock={nuevo}")
        elif not do_apply:
            print("=== Dry-run (--apply para ejecutar) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
