#!/usr/bin/env python3
"""Sincroniza maestra_maquinaria LC → tenant El Espino (equipos faltantes)."""
from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.environ.get("ERP_DEMO_WEB_ROOT", "/root/demo-web")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LC_DB = os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db")
ESPINO_DB = os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db")


def main() -> int:
    from erp_maquinaria import migrar_maestra_maquinaria, sincronizar_maestra_maquinaria_desde_lc

    if not os.path.isfile(ESPINO_DB):
        print(f"ERROR: Espino DB not found: {ESPINO_DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(ESPINO_DB)
    try:
        before = conn.execute("SELECT COUNT(*) FROM maestra_maquinaria").fetchone()[0]
        migrar_maestra_maquinaria(conn)
        added = sincronizar_maestra_maquinaria_desde_lc(conn, LC_DB)
        after = conn.execute("SELECT COUNT(*) FROM maestra_maquinaria").fetchone()[0]
    finally:
        conn.close()
    print(f"OK — maestra_maquinaria Espino: {before} → {after} (+{added} nuevos desde LC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
