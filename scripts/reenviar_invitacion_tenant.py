#!/usr/bin/env python3
"""Reenvía invitación por tenant (clave nueva solo en el correo).

Uso en VPS:
  python3 /root/scripts/reenviar_invitacion_tenant.py espino pruzzoduilio@ejemplo.cl
  python3 /root/scripts/reenviar_invitacion_tenant.py espino --buscar pruzzo
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.environ.get("ERP_DEMO_WEB_ROOT", "/root/demo-web")
MASTER_ROOT = os.environ.get("ERP_MASTER_ROOT", "/root/erp_master")
for p in (ROOT, os.path.join(ROOT, "demo_web"), MASTER_ROOT):
    if p and p not in sys.path and os.path.isdir(p):
        sys.path.insert(0, p)


def _tenant(slug: str) -> dict:
    from demo_web.tenants import get_tenant

    t = get_tenant(slug)
    if not t:
        raise SystemExit(f"Tenant desconocido: {slug}")
    return {
        "slug": t["slug"],
        "nombre": t.get("nombre") or slug,
        "nombre_erp": t.get("nombre_erp") or "",
        "db": t["db"],
        "secrets": t["secrets"],
        "kind": "lc" if t.get("erp_app") == "concepcion" else "demo",
    }


def _find_email(db_path: str, fragment: str) -> str:
    frag = (fragment or "").strip().lower()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT email FROM usuarios WHERE lower(email) LIKE ? ORDER BY email",
            (f"%{frag}%",),
        ).fetchall()
    if not rows:
        raise SystemExit(f"Sin usuarios que coincidan con «{fragment}» en {db_path}")
    if len(rows) > 1:
        print("Varios coinciden:", ", ".join(r[0] for r in rows))
        raise SystemExit("Indique el correo completo.")
    return str(rows[0][0])


def _user_id(db_path: str, email: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM usuarios WHERE lower(email)=?",
            (email.strip().lower(),),
        ).fetchone()
    if not row:
        raise SystemExit(f"Usuario no encontrado: {email}")
    return int(row[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Reenviar invitación ERP agrícola")
    parser.add_argument("tenant", help="Slug tenant (espino, concepcion, demo)")
    parser.add_argument("email", nargs="?", help="Correo del usuario")
    parser.add_argument("--buscar", dest="buscar", help="Fragmento del correo si no lo recuerda")
    parser.add_argument(
        "--admin",
        default=os.environ.get("ERP_INVITACION_ADMIN", "osvaldolirac@gmail.com"),
        help="Correo admin en pie de invitación",
    )
    args = parser.parse_args()

    tenant = _tenant(args.tenant)
    email = (args.email or "").strip().lower()
    if not email and args.buscar:
        email = _find_email(tenant["db"], args.buscar)
    if not email:
        parser.error("Indique email o --buscar")

    uid = _user_id(tenant["db"], email)
    from erp_master.tenant_admin import resend_invitation

    ok, msg = resend_invitation(tenant, tenant["kind"], uid, args.admin)
    if ok:
        print(f"OK: {msg}")
    else:
        raise SystemExit(f"ERROR: {msg}")


if __name__ == "__main__":
    main()
