#!/usr/bin/env python3
"""Restaura tabla facturas desde respaldo (corrige migración prorrateo incorrecta).

Uso: python3 scripts/restore_facturas_espino.py /root/espino/erp_espino.db /path/to/backup.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    target = Path(sys.argv[1])
    backup = Path(sys.argv[2])
    do_apply = "--apply" in sys.argv
    if not target.is_file() or not backup.is_file():
        raise SystemExit("DB no encontrada")
    src = sqlite3.connect(str(backup))
    dst = sqlite3.connect(str(target))
    try:
        n_src = src.execute("SELECT COUNT(*) FROM facturas").fetchone()[0]
        n_dst = dst.execute("SELECT COUNT(*) FROM facturas").fetchone()[0]
        print(f"facturas backup={n_src} actual={n_dst}")
        if do_apply:
            dst.execute("DELETE FROM facturas")
            cols = [r[1] for r in src.execute("PRAGMA table_info(facturas)")]
            ph = ",".join("?" * len(cols))
            rows = src.execute(f"SELECT {','.join(cols)} FROM facturas").fetchall()
            dst.executemany(f"INSERT INTO facturas ({','.join(cols)}) VALUES ({ph})", rows)
            dst.commit()
            print(f"=== Restauradas {len(rows)} filas facturas ===")
        else:
            print("=== Dry-run (use --apply) ===")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
