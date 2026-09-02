#!/usr/bin/env python3
"""Bootstrap tenant El Espino (schema LC vacío + admin). No toca La Concepción."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/root/demo-web")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = Path("/root/espino/erp_espino.db")
DEFAULT_SECRETS = Path("/root/espino/.streamlit/secrets.toml")
DEFAULT_ADMIN = "osvaldolirac@gmail.com"
SOURCE_DB = Path(os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"))


def _copy_admin_hash(conn: sqlite3.Connection, email: str) -> str | None:
    if not SOURCE_DB.is_file():
        return None
    src = sqlite3.connect(SOURCE_DB)
    try:
        row = src.execute(
            "SELECT password FROM usuarios WHERE lower(email)=lower(?) LIMIT 1",
            (email,),
        ).fetchone()
        if not row or not row[0]:
            return None
        pw_hash = str(row[0])
        conn.execute("DELETE FROM usuarios")
        conn.execute(
            "INSERT INTO usuarios (email, password, rol) VALUES (?,?,?)",
            (email, pw_hash, "admin"),
        )
        conn.commit()
        return pw_hash[:12] + "…"
    finally:
        src.close()


def main() -> int:
    db_path = Path(os.environ.get("ERP_ESPINO_DB", str(DEFAULT_DB)))
    secrets = Path(os.environ.get("ERP_ESPINO_SECRETS", str(DEFAULT_SECRETS)))
    admin_email = (os.environ.get("ESPINO_ADMIN_EMAIL") or DEFAULT_ADMIN).strip()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    secrets.parent.mkdir(parents=True, exist_ok=True)
    if not secrets.is_file():
        lc_secrets = Path(os.environ.get("ERP_LC_SECRETS", "/root/.streamlit/secrets.toml"))
        if lc_secrets.is_file():
            shutil.copy2(lc_secrets, secrets)
        else:
            secrets.write_text("# SMTP opcional\n", encoding="utf-8")

    os.environ["ERP_APP"] = "concepcion"
    os.environ["ERP_DB"] = str(db_path)
    os.environ["ERP_DEMO_DB"] = str(db_path)

    fresh = not db_path.is_file()
    if fresh:
        db_path.touch()

    import app_concepcion as erp_mod

    erp_mod.NOMBRE_DB = str(db_path)
    erp_mod.inicializar_db()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM gastos_espino")
        conn.commit()
        hint = _copy_admin_hash(conn, admin_email)
        if not hint:
            raise SystemExit(f"no se encontró hash de {admin_email} en {SOURCE_DB}")
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
