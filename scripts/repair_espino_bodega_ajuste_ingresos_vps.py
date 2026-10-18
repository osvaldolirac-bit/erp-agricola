#!/usr/bin/env python3
"""Ingresos manuales bodega El Espino — cuadrar pool tras LC (Atlas + otros desfases)."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = "/root/espino/erp_espino.db"
FECHA_AJUSTE = "2026-10-16"
CC_INGRESO = "EL ESPINO"
MARCA = "AJUSTE_MANUAL_BODEGA_20261016"

# (producto, cantidad, motivo)
AJUSTES: tuple[tuple[str, float, str], ...] = (
    (
        "ATLAS 43 EC",
        0.8,
        "Cubrir aplicación LC 1,2 L (pool 0,4 L → saldo 0 tras imputación)",
    ),
    (
        "MAGNESIO EXPERT",
        5.0,
        "Kardex: salidas LC 25 L vs ingresos 20 L (pool −5 L)",
    ),
    (
        "EVOLUTION FIFTY",
        0.9,
        "Kardex: salidas LC 20,9 L vs ingresos 20 L (pool −0,9 L)",
    ),
)


def run(db_path: str, *, apply: bool) -> None:
    path = Path(db_path)
    if not path.is_file():
        raise SystemExit(f"No existe DB: {path}")

    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from demo_web.services.espino_bodega_stock import (
        registrar_movimiento_ingreso_bodega,
        sincronizar_inventario_desde_pool,
        stock_pool,
    )

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ya = conn.execute(
            "SELECT 1 FROM bitacora WHERE accion=? LIMIT 1",
            (MARCA,),
        ).fetchone()
        if ya:
            print(f"Ya aplicado ({MARCA}). Nada que hacer.")
            return

        plan: list[tuple[int, str, float, float, float, str]] = []
        for prod, cant, motivo in AJUSTES:
            row = conn.execute(
                "SELECT id, precio_medio, COALESCE(unidad_medida,'lt') FROM inventario WHERE UPPER(TRIM(producto))=?",
                (prod.upper(),),
            ).fetchone()
            if not row:
                raise SystemExit(f"Sin inventario: {prod}")
            pid = int(row[0])
            pool_antes = stock_pool(conn, pid)
            plan.append((pid, prod, cant, pool_antes, pool_antes + cant, motivo))
            print(f"{prod}: pool {pool_antes:.2f} + ingreso {cant:.2f} → {pool_antes + cant:.2f}  ({motivo})")

        if not apply:
            print("\nSimulación (--apply para escribir).")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak_ajuste_bodega_{ts}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

        detalle_parts = []
        for pid, prod, cant, pool_antes, pool_despues, motivo in plan:
            row = conn.execute(
                "SELECT precio_medio, COALESCE(unidad_medida,'lt') FROM inventario WHERE id=?",
                (pid,),
            ).fetchone()
            pmp, um = float(row[0] or 0), row[1]
            registrar_movimiento_ingreso_bodega(
                conn,
                producto_id=pid,
                cantidad=cant,
                fecha=FECHA_AJUSTE,
                precio_medio=pmp,
                unidad_medida=um,
                centro_costo=CC_INGRESO,
            )
            sincronizar_inventario_desde_pool(conn, pid)
            detalle_parts.append(f"{prod} +{cant} L")

        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                "repair_script",
                MARCA,
                "; ".join(detalle_parts),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        print("OK — ingresos registrados e inventario sincronizado.")
        for pid, prod, cant, pool_antes, pool_despues, _ in plan:
            print(f"  {prod}: pool final {stock_pool(conn, pid):.2f}")
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    run(args.db, apply=args.apply)


if __name__ == "__main__":
    main()
