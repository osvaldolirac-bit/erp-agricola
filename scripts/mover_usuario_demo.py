#!/usr/bin/env python3
"""Mueve un usuario de prueba entre tenants comerciales (SQLite por tenant)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "riomaipo_vps"))

from rmweb.tenants import get_tenant

EMAIL = (sys.argv[1] if len(sys.argv) > 1 else "iv.morenorojas@gmail.com").strip().lower()
FROM = (sys.argv[2] if len(sys.argv) > 2 else "comercial-demo").strip().lower()
TO = (sys.argv[3] if len(sys.argv) > 3 else "taller-demo").strip().lower()


def main() -> None:
    src = get_tenant(FROM)
    dst = get_tenant(TO)
    if not src or not dst:
        raise SystemExit(f"Tenant inválido: {FROM} -> {TO}")

    sdb = sqlite3.connect(src["db"])
    sdb.row_factory = sqlite3.Row
    row = sdb.execute(
        "SELECT * FROM usuarios WHERE lower(usuario)=lower(?)",
        (EMAIL,),
    ).fetchone()
    if not row:
        sdb.close()
        raise SystemExit(f"No existe {EMAIL} en {FROM}")

    user = dict(row)
    sdb.execute("DELETE FROM usuarios WHERE id=?", (user["id"],))
    sdb.commit()
    sdb.close()

    ddb = sqlite3.connect(dst["db"])
    cols = [c[1] for c in ddb.execute("PRAGMA table_info(usuarios)").fetchall()]
    if "tenant_slug" not in cols:
        ddb.execute("ALTER TABLE usuarios ADD COLUMN tenant_slug TEXT")
    ddb.execute("DELETE FROM usuarios WHERE lower(usuario)=lower(?)", (EMAIL,))
    fields = [
        "usuario",
        "salt",
        "clave_hash",
        "nombre",
        "tipo",
        "activo",
        "fecha_expira",
        "invitado_por",
        "tenant_slug",
        "alerta_24h_enviada",
        "alerta_vencido_enviada",
        "mail_riego_bitacora",
    ]
    payload = {k: user.get(k) for k in fields if k in user or k == "tenant_slug"}
    payload["tenant_slug"] = TO
    use = [k for k in fields if k in payload and k != "id"]
    placeholders = ",".join("?" * len(use))
    collist = ",".join(use)
    ddb.execute(
        f"INSERT INTO usuarios ({collist}) VALUES ({placeholders})",
        [payload[k] for k in use],
    )
    ddb.commit()
    ddb.close()
    print(f"OK · {EMAIL}: {FROM} → {TO} (tenant_slug={TO})")


if __name__ == "__main__":
    main()
