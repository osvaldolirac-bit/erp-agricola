#!/usr/bin/env python3
"""Elimina ppto/kg estimado legacy Cerezos (mantiene variedades).

Uso: python3 scripts/cleanup_ppto_cerezos_espino.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

LEGACY = ("CEREZOS", "EL ESPINO", "Cerezos")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(str(db))
    ph = ",".join("?" * len(LEGACY))
    for tbl, col in (("costos_ppto_temporada", "monto_ppto"), ("costos_kg_estimado_temporada", "kg_estimado")):
        rows = conn.execute(
            f"SELECT centro_costo, {col} FROM {tbl} WHERE UPPER(TRIM(centro_costo)) IN ({ph})",
            LEGACY,
        ).fetchall()
        for cc, val in rows:
            print(f"DELETE {tbl}: {cc} = {val}")
        if apply:
            conn.execute(
                f"DELETE FROM {tbl} WHERE UPPER(TRIM(centro_costo)) IN ({ph})",
                LEGACY,
            )
    if apply:
        conn.commit()
        print("=== Aplicado ===")
    else:
        print("=== Dry-run ===")
    conn.close()


if __name__ == "__main__":
    main()
