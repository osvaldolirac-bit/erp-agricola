#!/usr/bin/env python3
"""Renombra COT-1019 → COT-0024 (correlativo operativo Río Maipo)."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

DB = Path(os.environ.get("RIOMAIPO_DB", "/root/riomaipo/data/riomaipo_erp.db"))


def main() -> int:
    if not DB.is_file():
        print(f"BD no encontrada: {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    try:
        old, new = "COT-1019", "COT-0024"
        row = conn.execute("SELECT id FROM cotizaciones WHERE folio=?", (old,)).fetchone()
        if not row:
            print(f"No existe {old} (ya corregido o ausente).")
            return 0
        dup = conn.execute("SELECT id FROM cotizaciones WHERE folio=?", (new,)).fetchone()
        if dup:
            print(f"Ya existe {new}, no se puede renombrar.", file=sys.stderr)
            return 1
        conn.execute("UPDATE cotizaciones SET folio=? WHERE folio=?", (new, old))
        conn.execute(
            "UPDATE cuentas SET concepto=REPLACE(concepto, ?, ?) WHERE concepto LIKE ?",
            (old, new, f"%{old}%"),
        )
        conn.commit()
        print(f"OK — {old} → {new}")
        nxt = conn.execute(
            """
            SELECT MAX(CAST(substr(folio, 5) AS INTEGER)) FROM cotizaciones
            WHERE folio LIKE 'COT-%' AND CAST(substr(folio, 5) AS INTEGER) < 1000
            """
        ).fetchone()[0]
        print(f"Siguiente correlativo operativo: COT-{int(nxt or 0) + 1:04d}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
