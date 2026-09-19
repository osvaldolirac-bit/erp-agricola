#!/usr/bin/env python3
"""Actualiza ingrediente activo en libro_campo desde inventario/PPPL/SAG.

Uso en VPS:
  python3 /root/scripts/corregir_ingredientes_libro_campo.py espino
  python3 /root/scripts/corregir_ingredientes_libro_campo.py espino --n-app 3
  python3 /root/scripts/corregir_ingredientes_libro_campo.py concepcion
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.environ.get("ERP_DEMO_WEB_ROOT", "/root/demo-web")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TENANT_DBS = {
    "espino": os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db"),
    "concepcion": os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Corregir ingredientes activos en libro de campo")
    parser.add_argument("tenant", choices=sorted(TENANT_DBS), help="Tenant (espino, concepcion)")
    parser.add_argument("--n-app", type=int, help="Solo aplicación N° (opcional)")
    args = parser.parse_args()

    db_path = TENANT_DBS[args.tenant]
    if not os.path.isfile(db_path):
        print(f"ERROR: DB no encontrada: {db_path}", file=sys.stderr)
        return 1

    from erp_inventario_ia import corregir_ingredientes_libro_campo, resolver_ingrediente_activo

    conn = sqlite3.connect(db_path)
    try:
        if args.n_app is not None:
            rows = conn.execute(
                "SELECT id, producto, COALESCE(ingrediente,'') FROM libro_campo WHERE n_aplicacion=?",
                (args.n_app,),
            ).fetchall()
            n = 0
            for lid, producto, ing in rows:
                canon = resolver_ingrediente_activo(conn, producto)
                if canon and canon.strip().upper() != (ing or "").strip().upper():
                    conn.execute("UPDATE libro_campo SET ingrediente=? WHERE id=?", (canon, lid))
                    print(f"  id={lid} {producto}: {ing!r} → {canon!r}")
                    n += 1
            conn.commit()
            print(f"OK — {n} línea(s) actualizada(s) en app N° {args.n_app:05d}")
        else:
            before = conn.execute(
                "SELECT COUNT(*) FROM libro_campo WHERE ingrediente LIKE 'Por confirmar%'"
            ).fetchone()[0]
            corregir_ingredientes_libro_campo(conn)
            conn.commit()
            after = conn.execute(
                "SELECT COUNT(*) FROM libro_campo WHERE ingrediente LIKE 'Por confirmar%'"
            ).fetchone()[0]
            print(f"OK — 'Por confirmar' antes={before} después={after}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
