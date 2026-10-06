#!/usr/bin/env python3
"""Restaura flujo_ingresos_cc La Concepción desde backup (montos y notas)."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = Path("/root/erp_concepcion_v6.db")
BACKUP = Path("/root/erp_concepcion_v6.20260909_211001.pre_compras_fix.bak.db")
TEMPORADA = "2026-2027"


def main() -> None:
    if not ACTIVE.is_file():
        raise SystemExit(f"Falta BD activa: {ACTIVE}")
    if not BACKUP.is_file():
        raise SystemExit(f"Falta backup: {BACKUP}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snap = ACTIVE.with_suffix(f".pre_flujo_restore_{stamp}.db")
    shutil.copy2(ACTIVE, snap)
    print(f"Snapshot: {snap}")

    src = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
    dst = sqlite3.connect(ACTIVE)
    try:
        rows = src.execute(
            """
            SELECT centro_costo, anio, mes, monto, COALESCE(nota, '')
            FROM flujo_ingresos_cc
            WHERE temporada = ?
              AND (ABS(COALESCE(monto, 0)) > 0.01 OR TRIM(COALESCE(nota, '')) != '')
            """,
            (TEMPORADA,),
        ).fetchall()
        print(f"Filas a restaurar: {len(rows)}")
        for cc, anio, mes, monto, nota in rows:
            dst.execute(
                """
                INSERT INTO flujo_ingresos_cc
                    (temporada, centro_costo, anio, mes, monto, nota)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(temporada, centro_costo, anio, mes)
                DO UPDATE SET monto = excluded.monto, nota = excluded.nota
                """,
                (TEMPORADA, cc, int(anio), int(mes), float(monto or 0), str(nota or "")),
            )
        dst.commit()
        chk = dst.execute(
            """
            SELECT COUNT(*), SUM(monto), SUM(CASE WHEN TRIM(COALESCE(nota,''))!='' THEN 1 ELSE 0 END)
            FROM flujo_ingresos_cc
            WHERE temporada = ? AND ABS(COALESCE(monto,0)) > 0.01
            """,
            (TEMPORADA,),
        ).fetchone()
        print(f"Verificación activa: celdas con monto>0={chk[0]} suma={chk[1]:,.0f} notas={chk[2]}")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    main()
