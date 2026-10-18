#!/usr/bin/env python3
"""Recalcula inventario.stock bodega El Espino desde kardex (CC EL ESPINO + Cerezos)."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db")


def main() -> None:
    from demo_web.services.native import espino_bodega

    conn = sqlite3.connect(DB)
    try:
        stock_map = espino_bodega._stock_cc_map(conn)
        ids = conn.execute("SELECT id FROM inventario").fetchall()
        n = 0
        for (iid,) in ids:
            st = stock_map.get(int(iid), 0.0)
            conn.execute("UPDATE inventario SET stock = ? WHERE id = ?", (st, int(iid)))
            n += 1
        conn.commit()
        print(f"OK — {n} producto(s) en {DB}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
