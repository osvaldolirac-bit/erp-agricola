#!/usr/bin/env python3
"""Bootstrap tenant GlobalGAP consultor (DB + admin + tablas)."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/root/demo-web")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = Path("/root/globalgap/erp_globalgap.db")
DEFAULT_SECRETS = Path("/root/globalgap/.streamlit/secrets.toml")
DEFAULT_DOCS = Path("/root/globalgap/docs")


def _hash(password: str) -> str:
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def main() -> int:
    db_path = Path(os.environ.get("ERP_GLOBALGAP_DB", str(DEFAULT_DB)))
    secrets = Path(os.environ.get("ERP_GLOBALGAP_SECRETS", str(DEFAULT_SECRETS)))
    docs = Path(os.environ.get("ERP_GLOBALGAP_DOCS", str(DEFAULT_DOCS)))
    admin_email = (os.environ.get("GLOBALGAP_ADMIN_EMAIL") or "globalgap@erpmaster.cl").strip()
    admin_pass = os.environ.get("GLOBALGAP_ADMIN_PASSWORD") or "Globalgap2026!"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    secrets.parent.mkdir(parents=True, exist_ok=True)
    if not secrets.is_file():
        demo_secrets = Path("/root/demo/.streamlit/secrets.toml")
        if demo_secrets.is_file():
            shutil.copy2(demo_secrets, secrets)
        else:
            secrets.write_text("# SMTP opcional\n", encoding="utf-8")

    os.environ["ERP_APP"] = "demo"
    os.environ["ERP_DEMO_DB"] = str(db_path)

    if not db_path.is_file():
        src = Path("/root/demo/erp_demo.db")
        if src.is_file():
            shutil.copy2(src, db_path)
            print(f"copied seed db from {src}")
        else:
            import app_demo as demo_mod

            conn = sqlite3.connect(db_path)
            if hasattr(demo_mod, "inicializar_db"):
                demo_mod.inicializar_db(conn)
            conn.close()
            print("initialized empty db via app_demo.inicializar_db")

    conn = sqlite3.connect(db_path)
    try:
        from demo_web.services.gap_consultor import migrar_gap_consultor

        migrar_gap_consultor(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        pw_col = "password"
        if pw_col not in cols:
            raise SystemExit("tabla usuarios sin columna password")
        conn.execute(
            f"""INSERT INTO usuarios (email, {pw_col}, rol) VALUES (?,?,?)
                ON CONFLICT(email) DO UPDATE SET {pw_col}=excluded.{pw_col}, rol=excluded.rol""",
            (admin_email, _hash(admin_pass), "admin"),
        )
        conn.commit()
    finally:
        conn.close()

    print("GlobalGAP tenant listo")
    print(f"  DB: {db_path}")
    print(f"  Docs: {docs}")
    print(f"  Admin: {admin_email} / {admin_pass}")
    print("  URL: https://erpmaster.cl/agricola/globalgap/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
