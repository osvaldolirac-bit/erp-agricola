#!/usr/bin/env python3
"""Crea la tabla de pagos extras de Remuneraciones en La Concepción y El Espino."""
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
    from demo_web.services.remuneracion_extra import asegurar_tabla

    conn = sqlite3.connect(db)
    try:
        asegurar_tabla(conn)
        conn.commit()
        ok = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='remuneracion_extra'"
        ).fetchone()
        print(f"OK — remuneracion_extra {bool(ok)} {db}")
    finally:
        conn.close()


def main() -> None:
    for db in DBS:
        _migrar(db)


if __name__ == "__main__":
    main()
