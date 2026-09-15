#!/usr/bin/env python3
"""Sincroniza inventario.stock con kardex bodega El Espino.

- Con ingresos kardex (pool Cerezos/El Espino): stock = ing − salidas
- Sin kardex: stock = max(stock − salidas, 0) (legacy)

Uso: python3 scripts/patch_espino_sync_inventario_stock.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

POOL_CCS = ("CEREZOS", "EL ESPINO")


def _esperado(conn: sqlite3.Connection, pid: int, inv: float) -> tuple[float, str]:
    ph = ",".join("?" * len(POOL_CCS))
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
        return max(ing - sal, 0.0), f"kardex ing={ing} sal={sal}"
    if sal <= 1e-9:
        return inv, "sin movimientos"
    return max(inv - sal, 0.0), f"legacy inv={inv} sal={sal}"


def plan(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    for row in conn.execute("SELECT id, producto, COALESCE(stock, 0) AS stock FROM inventario ORDER BY id"):
        pid, prod, inv = int(row[0]), row[1], float(row[2] or 0)
        nuevo, det = _esperado(conn, pid, inv)
        if abs(nuevo - inv) > 1e-6:
            lines.append(f"UPDATE {prod}: {inv} → {nuevo} ({det})")
    return lines


def apply(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT id, COALESCE(stock, 0) FROM inventario"):
        pid, inv = int(row[0]), float(row[1] or 0)
        nuevo, _ = _esperado(conn, pid, inv)
        if abs(nuevo - inv) > 1e-6:
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
        print("=== Sync inventario Espino ===")
        for line in plan(conn):
            print(line)
        if do_apply:
            apply(conn)
            conn.commit()
            print("=== Aplicado ===")
        else:
            print("=== Dry-run (use --apply) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
