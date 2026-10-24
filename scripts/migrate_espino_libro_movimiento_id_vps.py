#!/usr/bin/env python3
"""Añade libro_campo.movimiento_id en La Concepción y El Espino (VPS)."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DBS = (
    os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"),
    os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db"),
)


def _migrar(db: str) -> None:
    from demo_web.services.lc_bodega_desfase import ensure_movimiento_id_column

    conn = sqlite3.connect(db)
    try:
        ensure_movimiento_id_column(conn)
        conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(libro_campo)").fetchall()]
        print("OK — libro_campo columns:", "movimiento_id" in cols, db)
    finally:
        conn.close()


def main() -> None:
    for db in DBS:
        _migrar(db)


if __name__ == "__main__":
    main()
