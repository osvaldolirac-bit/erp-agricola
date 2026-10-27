#!/usr/bin/env python3
"""Crea las tablas de cosecha en La Concepción y El Espino. No carga cuarteles ni fundas."""
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
    from demo_web.services.cosecha import asegurar_tablas

    conn = sqlite3.connect(db)
    try:
        asegurar_tablas(conn)
        conn.commit()
        ok = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cosecha_faena'"
        ).fetchone()
        faenas = conn.execute("SELECT COUNT(*) FROM cosecha_faena").fetchone()[0]
        print(f"OK — cosecha_faena {bool(ok)} filas {faenas} {db}")
    finally:
        conn.close()


def main() -> None:
    for db in DBS:
        _migrar(db)


if __name__ == "__main__":
    main()
