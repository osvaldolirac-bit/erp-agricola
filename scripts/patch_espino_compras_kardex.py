#!/usr/bin/env python3
"""Registra ingresos kardex bodega por compras (sin movimiento previo).

Compras agro actualiza inventario.stock pero no siempre crea movimiento Ingreso;
sin kardex el stock queda desacoplado de LC/salidas.

Uso: python3 scripts/patch_espino_compras_kardex.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

POOL_CCS = ("CEREZOS", "EL ESPINO")
CC_MOV = "Cerezos"


def plan(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    ph = ",".join("?" * len(POOL_CCS))
    for pid, prod, inv in conn.execute(
        "SELECT id, producto, COALESCE(stock, 0) FROM inventario ORDER BY producto"
    ):
        ing = float(
            conn.execute(
                f"""SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
                    WHERE producto_id=? AND tipo='Ingreso' AND UPPER(centro_costo) IN ({ph})""",
                (pid, *POOL_CCS),
            ).fetchone()[0]
            or 0
        )
        sal = float(
            conn.execute(
                "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
                (pid,),
            ).fetchone()[0]
            or 0
        )
        if ing > 1e-9:
            continue
        lc = float(
            conn.execute(
                "SELECT COALESCE(SUM(gasto_total), 0) FROM libro_campo WHERE UPPER(TRIM(producto))=?",
                (str(prod).upper().strip(),),
            ).fetchone()[0]
            or 0
        )
        # Cantidad ingresada ≈ stock actual + salidas (compras sin kardex)
        qty = max(float(inv) + sal, 0.0)
        if qty <= 1e-9 and lc <= 1e-9:
            continue
        if qty <= 1e-9 and lc > 0:
            qty = lc + float(inv)
        lines.append(f"INGRESO {prod}: +{qty} (stock={inv} sal={sal} lc={lc})")
    return lines


def apply(conn: sqlite3.Connection) -> None:
    ph = ",".join("?" * len(POOL_CCS))
    for pid, prod, inv in conn.execute(
        "SELECT id, producto, COALESCE(stock, 0) FROM inventario ORDER BY id"
    ):
        ing = float(
            conn.execute(
                f"""SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
                    WHERE producto_id=? AND tipo='Ingreso' AND UPPER(centro_costo) IN ({ph})""",
                (pid, *POOL_CCS),
            ).fetchone()[0]
            or 0
        )
        if ing > 1e-9:
            continue
        sal = float(
            conn.execute(
                "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
                (pid,),
            ).fetchone()[0]
            or 0
        )
        lc = float(
            conn.execute(
                "SELECT COALESCE(SUM(gasto_total), 0) FROM libro_campo WHERE UPPER(TRIM(producto))=?",
                (str(prod).upper().strip(),),
            ).fetchone()[0]
            or 0
        )
        qty = max(float(inv) + sal, 0.0)
        if qty <= 1e-9:
            continue
        row = conn.execute(
            "SELECT precio_medio, COALESCE(unidad_medida, 'L') FROM inventario WHERE id=?",
            (pid,),
        ).fetchone()
        pmp, um = float(row[0] or 0), row[1]
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, "Ingreso", qty, "2026-01-01", CC_MOV, qty * pmp, um),
        )
        nuevo = max(qty - sal, 0.0)
        conn.execute("UPDATE inventario SET stock=? WHERE id=?", (nuevo, pid))


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
        for line in plan(conn):
            print(line)
        if do_apply:
            apply(conn)
            conn.commit()
            print("=== Aplicado ===")
        else:
            print("=== Dry-run ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
