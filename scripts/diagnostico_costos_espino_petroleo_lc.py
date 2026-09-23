#!/usr/bin/env python3
"""Verifica salidas petróleo imputadas a EL ESPINO en BD LC."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    db_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT fecha, vehiculo, litros, valor_imputado
           FROM petroleo
           WHERE tipo = 'Salida'
             AND UPPER(TRIM(COALESCE(centro_costo, ''))) = 'EL ESPINO'
           ORDER BY fecha DESC"""
    ).fetchall()
    total = sum(float(r[3] or 0) for r in rows)
    print(f"Salidas petróleo EL ESPINO: {len(rows)} registros, total ${total:,.0f}")
    for fecha, veh, litros, val in rows[:10]:
        print(f"  {fecha} | {veh or '-'} | {litros or 0} L | ${float(val or 0):,.0f}")
    conn.close()


if __name__ == "__main__":
    main()
