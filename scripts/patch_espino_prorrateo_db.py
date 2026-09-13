#!/usr/bin/env python3
"""Aplica prorrateo Espino por superficie ha y elimina CC legacy (ej. Cerezos)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

VARIEDADES_ESPINO = ("ROYAL DOWN", "SWEET ARYANA", "SANTINA")
SUPERFICIE_HA_ESPINO = {
    "SWEET ARYANA": 1.0,
    "ROYAL DOWN": 1.5,
    "SANTINA": 4.5,
}
DEFAULT_DB = Path("/root/espino/erp_espino.db")


def prorrateo_pct_espino() -> dict[str, float]:
    total_ha = sum(SUPERFICIE_HA_ESPINO.get(v, 0.0) for v in VARIEDADES_ESPINO)
    pcts = {
        v: round(100.0 * SUPERFICIE_HA_ESPINO.get(v, 0.0) / total_ha, 2)
        for v in VARIEDADES_ESPINO[:-1]
    }
    pcts[VARIEDADES_ESPINO[-1]] = round(100.0 - sum(pcts.values()), 2)
    return pcts


def patch(db_path: Path) -> None:
    pcts = prorrateo_pct_espino()
    oficial = {v.upper() for v in VARIEDADES_ESPINO}
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prorrateo_cc (
                centro_costo TEXT PRIMARY KEY,
                porcentaje REAL NOT NULL,
                superficie_ha REAL DEFAULT 0
            )"""
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
        if "superficie_ha" not in cols:
            conn.execute(
                "ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0"
            )
        rows = conn.execute("SELECT centro_costo FROM prorrateo_cc").fetchall()
        legacy = [str(r[0]) for r in rows if str(r[0]).upper() not in oficial]
        for cc in legacy:
            conn.execute("DELETE FROM prorrateo_cc WHERE centro_costo = ?", (cc,))
        for cc in VARIEDADES_ESPINO:
            conn.execute(
                """INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha)
                   VALUES (?,?,?)
                   ON CONFLICT(centro_costo) DO UPDATE SET
                     porcentaje=excluded.porcentaje,
                     superficie_ha=excluded.superficie_ha""",
                (cc, float(pcts[cc]), float(SUPERFICIE_HA_ESPINO.get(cc, 0))),
            )
        conn.commit()
        print("Prorrateo Espino aplicado:")
        for r in conn.execute(
            "SELECT centro_costo, porcentaje, superficie_ha FROM prorrateo_cc ORDER BY centro_costo"
        ):
            print(f"  {r[0]}: {r[1]:.2f}% · {r[2]:.1f} ha")
        if legacy:
            print("Eliminados legacy:", ", ".join(legacy))
    finally:
        conn.close()


if __name__ == "__main__":
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    if not db.is_file():
        raise SystemExit(f"No existe BD: {db}")
    patch(db)
