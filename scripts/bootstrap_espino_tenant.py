#!/usr/bin/env python3
"""Bootstrap tenant El Espino (schema LC vacío + admin). No toca La Concepción."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

DEFAULT_DB = Path("/root/espino/erp_espino.db")
DEFAULT_SECRETS = Path("/root/espino/.streamlit/secrets.toml")
DEFAULT_ADMIN = "osvaldolirac@gmail.com"
SOURCE_DB = Path(os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))


def _schema_clone(source: Path, dest: Path) -> None:
    if dest.is_file():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["sqlite3", str(source), ".schema"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"schema dump failed: {proc.stderr}")
    lines = [
        ln
        for ln in proc.stdout.splitlines()
        if ln.strip() and "sqlite_sequence" not in ln.lower()
    ]
    ddl = "\n".join(lines)
    conn = sqlite3.connect(dest)
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def _copy_admin_hash(conn: sqlite3.Connection, email: str) -> None:
    if not SOURCE_DB.is_file():
        raise RuntimeError(f"source db missing: {SOURCE_DB}")
    src = sqlite3.connect(SOURCE_DB)
    try:
        row = src.execute(
            "SELECT password FROM usuarios WHERE lower(email)=lower(?) LIMIT 1",
            (email,),
        ).fetchone()
        if not row or not row[0]:
            raise RuntimeError(f"no password hash for {email} in {SOURCE_DB}")
        pw_hash = str(row[0])
        conn.execute("DELETE FROM usuarios")
        conn.execute(
            "INSERT INTO usuarios (email, password, rol) VALUES (?,?,?)",
            (email, pw_hash, "admin"),
        )
        conn.commit()
    finally:
        src.close()


def main() -> int:
    db_path = Path(os.environ.get("ERP_ESPINO_DB", str(DEFAULT_DB)))
    secrets = Path(os.environ.get("ERP_ESPINO_SECRETS", str(DEFAULT_SECRETS)))
    admin_email = (os.environ.get("ESPINO_ADMIN_EMAIL") or DEFAULT_ADMIN).strip()

    secrets.parent.mkdir(parents=True, exist_ok=True)
    if not secrets.is_file():
        lc_secrets = Path(os.environ.get("ERP_LC_SECRETS", "/root/.streamlit/secrets.toml"))
        if lc_secrets.is_file():
            shutil.copy2(lc_secrets, secrets)
        else:
            secrets.write_text("# SMTP opcional\n", encoding="utf-8")

    if not SOURCE_DB.is_file():
        raise SystemExit(f"SOURCE_DB not found: {SOURCE_DB}")

    _schema_clone(SOURCE_DB, db_path)

    conn = sqlite3.connect(db_path)
    try:
        for tbl in ("gastos_espino", "facturas", "movimientos", "petroleo", "libro_campo"):
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        _copy_admin_hash(conn, admin_email)
    finally:
        conn.close()

    print("Tenant El Espino listo")
    print(f"  DB: {db_path}")
    print(f"  Secrets: {secrets}")
    print(f"  Admin: {admin_email} (misma clave que en LC/demo)")
    print("  URL: https://erpmaster.cl/agricola/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
