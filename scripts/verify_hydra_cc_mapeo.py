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


def _centros_costo_lc(db_path: str) -> set[str]:
    out: set[str] = set()
    try:
        from demo_web.services.streamlit_mock import install_streamlit_mock

        install_streamlit_mock()
        import app_concepcion as erp  # noqa: WPS433

        erp.NOMBRE_DB = db_path
        out = {
            str(c).strip().upper()
            for c in (getattr(erp, "CENTROS_COSTO", []) or [])
            if str(c).strip()
        }
    except Exception as exc:
        print(f"CENTROS_COSTO vía app: {exc} — uso prorrateo_cc")
    if out:
        return out
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT DISTINCT TRIM(centro_costo) FROM prorrateo_cc WHERE TRIM(centro_costo)<>''"
        ).fetchall()
        conn.close()
        return {str(r[0]).strip().upper() for r in rows if r[0]}
    except Exception:
        return set()


def main() -> int:
    db = Path(LC_DB)
    if not db.is_file():
        print(f"SKIP: no BD en {db}")
        return 0
    conn = sqlite3.connect(str(db))
    cc_erp = _centros_costo_lc(str(db))

    try:
        conn.execute("SELECT 1 FROM hydrawise_zona LIMIT 1")
    except sqlite3.OperationalError:
        print("Tabla hydrawise_zona no existe aún (sin import Hydra).")
        conn.close()
        return 0

    rows = conn.execute(
        """SELECT relay_id, nombre_hw, alias, huerto_cc, activo, COALESCE(link_riego, 1)
           FROM hydrawise_zona ORDER BY relay_id"""
    ).fetchall()
    if not rows:
        print("Sin sectores importados (hydrawise_zona vacía).")
        conn.close()
        return 0

    n_link = 0
    print(f"Sectores importados: {len(rows)}")
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
        en_link = activo and lnk and cc_u and ok_cc
        if en_link:
            n_link += 1
        tag = "link" if en_link else "—"
        print(f"  [{tag:4}] {rid:5} {(nom or '')[:28]:28} {st}")
    print("-" * 72)
    print(f"En link regador (activo + CC válido): {n_link}")
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
