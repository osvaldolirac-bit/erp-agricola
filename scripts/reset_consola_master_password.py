#!/usr/bin/env python3
"""Resetea clave Super Consola (master_usuarios) en el VPS."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys

DB = os.environ.get("ERP_MASTER_DB", "/root/erp_master.db")
EMAIL = (os.environ.get("ERP_MASTER_SEED_EMAIL") or "osvaldolirac@gmail.com").strip().lower()
PASSWORD = os.environ.get("ERP_MASTER_SEED_PASSWORD") or "Erpmaster2026"


def hash_password(password: str) -> str:
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) >= 2:
        email = sys.argv[1].strip().lower()
    else:
        email = EMAIL
    pwd = sys.argv[2] if len(sys.argv) >= 3 else PASSWORD
    conn = sqlite3.connect(DB)
    cur = conn.execute(
        "UPDATE master_usuarios SET password=? WHERE lower(email)=?",
        (hash_password(pwd), email),
    )
    conn.commit()
    if cur.rowcount == 0:
        print(f"No user found: {email}", file=sys.stderr)
        return 1
    print(f"OK password reset for {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
