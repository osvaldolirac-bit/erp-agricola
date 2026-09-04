#!/usr/bin/env python3
"""Repara Tesorería LC: Paola, aplicación tracto, gastos_espino históricos."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"

from demo_web.services.tesoreria_cxp import saldo_cxp_neto, sql_imputado_costos_subquery, sql_solo_cxp_tesoreria  # noqa: E402
from demo_web.services.tesoreria_reparar_lc import (  # noqa: E402
    aplicar_fix_sqlite_directo,
    sql_buscar_aplicacion_tracto_historica_pendiente,
    sql_buscar_arriendos_paola_pendientes,
    sql_buscar_facturas_gastos_espino_pendientes,
    sql_buscar_montos_canonicos_lc_pendientes,
)


def _listar(conn, titulo: str, sql: str) -> None:
    print(f"\n=== {titulo} ===")
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError as e:
        print(f"(skip: {e})")
        return
    if not rows:
        print("(ninguno)")
        return
    for r in rows:
        print(r)


def _deuda_neta(conn) -> float:
    imp = sql_imputado_costos_subquery("f")
    rows = conn.execute(
        f"""
        SELECT f.monto_total, f.monto_pagado, {imp} AS imp
        FROM facturas f
        WHERE TRIM(COALESCE(f.estado,'')) = 'Pendiente'
          AND f.monto_total > 0
          {sql_solo_cxp_tesoreria('f')}
        """
    ).fetchall()
    return sum(saldo_cxp_neto(r[0], r[1], r[2]) for r in rows)


def main() -> int:
    print(f"DB: {DB}")
    conn = sqlite3.connect(DB)
    try:
        _listar(conn, "Paola pendiente (antes)", sql_buscar_arriendos_paola_pendientes())
        _listar(conn, "Aplicación tracto pendiente (antes)", sql_buscar_aplicacion_tracto_historica_pendiente())
        _listar(conn, "Match gastos_espino pendiente (antes)", sql_buscar_facturas_gastos_espino_pendientes())
        _listar(conn, "Canónicos LC pendiente (antes)", sql_buscar_montos_canonicos_lc_pendientes())
        print(f"\nDeuda neta CxP (antes): ${_deuda_neta():,.0f}")
    finally:
        conn.close()

    n = aplicar_fix_sqlite_directo(DB)
    print(f"\nCorregidas: {n} fila(s)")

    conn = sqlite3.connect(DB)
    try:
        _listar(conn, "Paola pendiente (después)", sql_buscar_arriendos_paola_pendientes())
        _listar(conn, "Aplicación tracto pendiente (después)", sql_buscar_aplicacion_tracto_historica_pendiente())
        print(f"\nDeuda neta CxP (después): ${_deuda_neta():,.0f}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
