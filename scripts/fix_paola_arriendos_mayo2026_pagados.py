#!/usr/bin/env python3
"""Marca arriendos María Paola may-2026 como Pagado (sin depender de streamlit)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"

from demo_web.services.arriendos_pagados_lc import (  # noqa: E402
    aplicar_fix_sqlite_directo,
    sql_buscar_arriendos_paola_mayo2026_pendientes,
)


def main() -> int:
    print(f"DB: {DB}")
    conn = sqlite3.connect(DB)
    try:
        print("\n=== Pendientes Paola (antes) ===")
        for r in conn.execute(sql_buscar_arriendos_paola_mayo2026_pendientes()).fetchall():
            print(r)
    finally:
        conn.close()

    n = aplicar_fix_sqlite_directo(DB)
    print(f"\nCorregidas: {n} fila(s)")

    conn = sqlite3.connect(DB)
    try:
        print("\n=== Pendientes Paola (después) ===")
        rest = conn.execute(sql_buscar_arriendos_paola_mayo2026_pendientes()).fetchall()
        if rest:
            for r in rest:
                print("AÚN PENDIENTE:", r)
            return 1
        print("(ninguno)")

        pend = conn.execute(
            """
            SELECT COALESCE(SUM(
              MAX(0, monto_total - COALESCE(monto_pagado, 0))
            ), 0)
            FROM facturas
            WHERE TRIM(COALESCE(estado,'')) = 'Pendiente'
              AND nro_documento NOT LIKE '%_P' AND monto_total > 0
              AND UPPER(TRIM(nro_documento)) NOT GLOB 'INT-*'
              AND UPPER(TRIM(nro_documento)) NOT GLOB 'GE-*'
            """
        ).fetchone()[0]
        print(f"\nDeuda CxP pendiente (sin INT-/GE-): ${float(pend):,.0f}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
