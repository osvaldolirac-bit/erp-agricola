#!/usr/bin/env python3
"""Copia cuentas de usuarios LC → tenant Espino (misma clave, sin datos operativos)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SOURCE_DB = Path(os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))
ESPINO_DB = Path(os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db"))


def _usuario_columns(conn: sqlite3.Connection) -> list[str]:
    return [str(r[1]) for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()]


def sync_users() -> int:
    if not SOURCE_DB.is_file():
        raise SystemExit(f"LC DB not found: {SOURCE_DB}")
    if not ESPINO_DB.is_file():
        raise SystemExit(f"Espino DB not found: {ESPINO_DB}")

    src = sqlite3.connect(SOURCE_DB)
    dst = sqlite3.connect(ESPINO_DB)
    try:
        src_cols = _usuario_columns(src)
        dst_cols = set(_usuario_columns(dst))
        cols = [c for c in src_cols if c in dst_cols]
        if "email" not in cols or "password" not in cols:
            raise SystemExit("usuarios table missing email/password")

        rows = src.execute(
            f"SELECT {', '.join(cols)} FROM usuarios ORDER BY lower(email)"
        ).fetchall()
        dst.execute("DELETE FROM usuarios")
        placeholders = ", ".join("?" for _ in cols)
        dst.executemany(
            f"INSERT INTO usuarios ({', '.join(cols)}) VALUES ({placeholders})",
            rows,
        )
        dst.commit()
        n = dst.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        print(f"synced {n} user(s) from {SOURCE_DB} -> {ESPINO_DB}")
        for em, rol in dst.execute("SELECT email, COALESCE(rol,'operador') FROM usuarios ORDER BY email"):
            print(f"  - {em} ({rol})")
        return n
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    raise SystemExit(0 if sync_users() else 1)
