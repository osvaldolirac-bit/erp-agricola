#!/usr/bin/env python3
"""Repara ingresos kardex faltantes desde facturas agro LC (sin duplicar stock)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ERP_APP", "concepcion")
os.environ.setdefault("ERP_DB", os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))


def main() -> int:
    from demo_web.services.lc_bodega_compras_kardex import reparar_compras_agro_recientes

    import sqlite3

    db = os.environ["ERP_DB"]
    conn = sqlite3.connect(db)
    try:
        msgs = reparar_compras_agro_recientes(conn, dias=365, dry_run="--dry-run" in sys.argv)
        if not msgs:
            print("Nada que reparar (ingresos kardex ya existen).")
        else:
            for m in msgs:
                print(m)
        if "--dry-run" not in sys.argv:
            conn.commit()
            print(f"OK — {len(msgs)} línea(s) aplicadas en {db}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
