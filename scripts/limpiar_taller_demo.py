#!/usr/bin/env python3
"""Limpia datos ficticios del tenant taller-demo dejando empresa, parámetros y usuarios."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/riomaipo/data/taller_demo.db")
KEEP = frozenset({"empresa", "parametros", "usuarios", "schema_meta"})


def main() -> None:
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = OFF")
    cur = db.cursor()
    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    cleared: list[tuple[str, int]] = []
    for table in tables:
        if table in KEEP:
            continue
        count = cur.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        if count:
            cur.execute(f"DELETE FROM [{table}]")
            cleared.append((table, count))

    cur.execute("DELETE FROM sqlite_sequence")
    cur.execute(
        """
        UPDATE empresa
        SET rut='76.000.000-1', razon_social='DEMO Taller Automotriz'
        WHERE id=1
        """
    )
    db.execute("PRAGMA foreign_keys = ON")
    db.commit()
    db.execute("VACUUM")

    print(f"OK · {DB}")
    print("Tablas limpiadas:")
    for table, count in sorted(cleared):
        print(f"  {table}: {count}")
    print("Conteo final (tablas con datos):")
    for table in sorted(tables):
        count = cur.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        if count:
            print(f"  {table}: {count}")
    db.close()


if __name__ == "__main__":
    main()
