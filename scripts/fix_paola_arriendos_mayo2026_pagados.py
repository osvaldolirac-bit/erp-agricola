#!/usr/bin/env python3
"""Reclasifica facturas gastos_espino mal etiquetadas en LC (→ razón social El Espino)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Repo root: script en scripts/ → parents[1]; en VPS /root/scripts → usar demo-web
for candidate in (
    Path(__file__).resolve().parents[1],
    Path("/root/demo-web"),
):
    if (candidate / "demo_web" / "services" / "tesoreria_reparar_lc.py").is_file():
        sys.path.insert(0, str(candidate))
        break

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"

from demo_web.services.tesoreria_cxp import saldo_cxp_neto, sql_imputado_costos_subquery, sql_solo_cxp_tesoreria  # noqa: E402
from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino  # noqa: E402
from demo_web.services.tesoreria_reparar_lc import (  # noqa: E402
    aplicar_fix_sqlite_directo,
    sql_buscar_aplicacion_tracto_historica_pendiente,
    sql_buscar_arriendos_paola_pendientes,
    sql_buscar_facturas_gastos_espino_mal_clasificadas,
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


def _deuda_neta_lc(conn) -> float:
    imp = sql_imputado_costos_subquery("f")
    excl = sql_and_excluir_razon_social_espino("razon_social", alias="f")
    rows = conn.execute(
        f"""
        SELECT f.monto_total, f.monto_pagado, {imp} AS imp
        FROM facturas f
        WHERE TRIM(COALESCE(f.estado,'')) = 'Pendiente'
          AND f.monto_total > 0
          {sql_solo_cxp_tesoreria('f')}
          {excl}
        """
    ).fetchall()
    return sum(saldo_cxp_neto(r[0], r[1], r[2]) for r in rows)


def main() -> int:
    print(f"DB: {DB}")
    conn = sqlite3.connect(DB)
    try:
        _listar(conn, "gastos_espino mal clasificados (antes)", sql_buscar_facturas_gastos_espino_mal_clasificadas())
        _listar(conn, "Paola mal clasificada (antes)", sql_buscar_arriendos_paola_pendientes())
        _listar(conn, "Tracto/aplicación mal clasificada (antes)", sql_buscar_aplicacion_tracto_historica_pendiente())
        print(f"\nDeuda neta CxP LC (antes): ${_deuda_neta_lc(conn):,.0f}")
    finally:
        conn.close()

    n = aplicar_fix_sqlite_directo(DB)
    print(f"\nReclasificadas a El Espino: {n} fila(s)")

    conn = sqlite3.connect(DB)
    try:
        _listar(conn, "gastos_espino mal clasificados (después)", sql_buscar_facturas_gastos_espino_mal_clasificadas())
        _listar(conn, "Paola mal clasificada (después)", sql_buscar_arriendos_paola_pendientes())
        print(f"\nDeuda neta CxP LC (después): ${_deuda_neta_lc(conn):,.0f}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
