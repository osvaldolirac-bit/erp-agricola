#!/usr/bin/env python3
"""Alinea inventario.stock al kardex bodega El Espino (ing Cerezos/CEREZOS/EL ESPINO − salidas)."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = "/root/espino/erp_espino.db"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    path = Path(args.db)
    if not path.is_file():
        raise SystemExit(f"No existe DB: {path}")

    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from demo_web.services.espino_bodega_stock import sincronizar_inventario_desde_pool, stock_pool

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT i.id, i.producto, i.stock AS inv,
                      (SELECT COUNT(*) FROM movimientos m WHERE m.producto_id=i.id) AS n_mov
               FROM inventario i ORDER BY i.producto"""
        ).fetchall()
        cambios = []
        for r in rows:
            pid = int(r["id"])
            if int(r["n_mov"] or 0) == 0:
                continue
            pool = stock_pool(conn, pid)
            inv = float(r["inv"] or 0)
            if abs(inv - pool) > 1e-4:
                cambios.append((r["producto"], inv, pool))

        print(f"Productos con kardex y desfase inventario↔pool: {len(cambios)}")
        for prod, inv, pool in cambios[:40]:
            print(f"  {prod}: inventario {inv} → pool {pool}")
        if len(cambios) > 40:
            print(f"  ... y {len(cambios) - 40} más")

        if not args.apply:
            print("\nSimulación (--apply para escribir).")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak_sync_stock_{ts}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

        n = sincronizar_inventario_desde_pool(conn)
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                "sync_script",
                "SYNC STOCK BODEGA ESPINO",
                f"inventario.stock alineado a kardex ({n} productos)",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        print(f"OK — {n} producto(s) sincronizados.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
