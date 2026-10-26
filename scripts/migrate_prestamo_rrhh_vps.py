#!/usr/bin/env python3
"""Arma el libro mayor de préstamos RRHH en La Concepción y El Espino."""
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
    from demo_web.services.prestamo_rrhh import migrar_desde_ficha, reflejar_todos

    conn = sqlite3.connect(db)
    try:
        nuevos = migrar_desde_ficha(conn)
        reflejar_todos(conn)
        conn.commit()
        prestamos = conn.execute("SELECT COUNT(*) FROM prestamo_rrhh").fetchone()[0]
        abonos = conn.execute("SELECT COUNT(*) FROM prestamo_rrhh_abono").fetchone()[0]
        print(f"OK — prestamos {prestamos} abonos {abonos} nuevos {nuevos} {db}")
    finally:
        conn.close()


def main() -> None:
    for db in DBS:
        _migrar(db)


if __name__ == "__main__":
    main()
