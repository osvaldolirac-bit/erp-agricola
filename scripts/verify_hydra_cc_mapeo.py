#!/usr/bin/env python3
"""Verifica mapeo sector Hydrawise → CC (BD La Concepción)."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LC_DB = os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db")


def main() -> int:
    db = Path(LC_DB)
    if not db.is_file():
        print(f"SKIP: no BD en {db}")
        return 0
    conn = sqlite3.connect(str(db))
    os.environ["ERP_APP"] = "concepcion"
    os.environ["ERP_DB"] = str(db)
    from demo_web.services.erp_loader import bind_tenant_context, get_erp_module

    bind_tenant_context("concepcion")
    demo = get_erp_module()
    cc_erp = {str(c).strip().upper() for c in (getattr(demo, "CENTROS_COSTO", []) or []) if str(c).strip()}

    rows = conn.execute(
        """SELECT relay_id, nombre_hw, alias, huerto_cc, activo, COALESCE(link_riego, 1)
           FROM hydrawise_zona ORDER BY relay_id"""
    ).fetchall()
    if not rows:
        print("Sin sectores importados (hydrawise_zona vacía).")
        return 0

    from demo_web.services.hydrawise_riego import sectores_para_link_riego

    link = sectores_para_link_riego(conn)
    print(f"Sectores importados: {len(rows)} | En link riego: {len(link)}")
    print("-" * 72)
    bad = 0
    sin_cc = 0
    for rid, nom, alias, cc, activo, lnk in rows:
        cc_u = (cc or "").strip().upper()
        ok_cc = cc_u in cc_erp if cc_u else False
        if not cc_u:
            sin_cc += 1
            st = "SIN CC"
        elif not ok_cc:
            bad += 1
            st = f"CC NO EN ERP: {cc_u!r}"
        else:
            st = f"OK → {cc_u}"
        en_link = "link" if (activo and lnk and cc_u and ok_cc) else "—"
        print(f"  [{en_link:4}] {rid:5} {nom[:28]:28} {st}")
    print("-" * 72)
    if sin_cc:
        print(f"⚠ {sin_cc} sector(es) sin CC — no aparecen en link ni sync imputable.")
    if bad:
        print(f"⚠ {bad} CC fuera de CENTROS_COSTO ERP — corrija en HYDRA.")
    if not sin_cc and not bad:
        print("✓ Todos los sectores con CC válido en ERP.")
    conn.close()
    return 1 if (bad or sin_cc) else 0


if __name__ == "__main__":
    raise SystemExit(main())
