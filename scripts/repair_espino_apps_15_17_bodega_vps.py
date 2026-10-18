#!/usr/bin/env python3
"""Rebaja bodega faltante: Apps 15–17 (2026-10-03) guardadas sin movimientos Salida."""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = "/root/espino/erp_espino.db"
APPS = (15, 16, 17)
FECHA_ESPERADA = "2026-10-03"
CC_BODEGA = "EL ESPINO"


def _match_mov(
    conn: sqlite3.Connection,
    *,
    producto_id: int,
    cantidad: float,
    fecha: str,
    centro_costo: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT m.id FROM movimientos m
           WHERE m.tipo='Salida' AND m.producto_id=? AND m.fecha=?
             AND UPPER(TRIM(m.centro_costo))=?
             AND ABS(m.cantidad - ?) < 1e-4
           LIMIT 1""",
        (producto_id, fecha, centro_costo.upper().strip(), cantidad),
    ).fetchone()


def _producto_id(conn: sqlite3.Connection, nombre: str) -> int:
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(TRIM(producto))=?",
        (nombre.upper().strip(),),
    ).fetchone()
    if not row:
        raise SystemExit(f"Producto no encontrado en inventario: {nombre}")
    return int(row[0])


def run(db_path: str, *, apply: bool) -> None:
    path = Path(db_path)
    if not path.is_file():
        raise SystemExit(f"No existe DB: {path}")

    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from demo_web.services.espino_scope import normalizar_cuartel_espino

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    inserts: list[tuple] = []
    try:
        for n_app in APPS:
            lc = conn.execute(
                """SELECT id, n_aplicacion, fecha, sector, producto, gasto_total
                   FROM libro_campo WHERE n_aplicacion=? ORDER BY id""",
                (n_app,),
            ).fetchall()
            if not lc:
                raise SystemExit(f"App {n_app}: sin líneas en libro_campo")
            fecha = str(lc[0]["fecha"])[:10]
            if fecha != FECHA_ESPERADA:
                print(f"  App {n_app}: fecha libro {fecha} (esperada {FECHA_ESPERADA})")
            sector = normalizar_cuartel_espino(str(lc[0]["sector"] or "")) or str(
                lc[0]["sector"] or ""
            ).strip()
            print(f"App N°{n_app} · {fecha} · sector {sector} · {len(lc)} línea(s)")
            for line in lc:
                prod = str(line["producto"] or "").strip()
                cant = float(line["gasto_total"] or 0)
                if cant <= 0:
                    raise SystemExit(f"App {n_app} línea {line['id']}: gasto_total inválido")
                pid = _producto_id(conn, prod)
                cc = normalizar_cuartel_espino(str(line["sector"] or "")) or sector
                existing = _match_mov(
                    conn,
                    producto_id=pid,
                    cantidad=cant,
                    fecha=fecha,
                    centro_costo=cc,
                )
                if existing:
                    print(f"  OK mov id={existing['id']} · {prod} {cant} → {cc}")
                    continue
                row = conn.execute(
                    "SELECT precio_medio, COALESCE(unidad_medida,'kg') FROM inventario WHERE id=?",
                    (pid,),
                ).fetchone()
                pmp = float(row[0] or 0)
                um = row[1]
                print(f"  + INSERT Salida · {prod} −{cant} {um} · CC {cc}")
                inserts.append(
                    (pid, "Salida", cant, fecha, cc, cant * pmp, um, n_app, prod)
                )

        if not inserts:
            print("\nNada que insertar (salidas ya existen).")
            return
        if not apply:
            print(f"\nSimulación: {len(inserts)} movimiento(s) pendientes (--apply para escribir).")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak_apps151617_{ts}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")

        for pid, tipo, cant, fecha, cc, valor, um, n_app, prod in inserts:
            conn.execute(
                """INSERT INTO movimientos
                   (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
                   VALUES (?,?,?,?,?,?,?)""",
                (pid, tipo, cant, fecha, cc, valor, um),
            )
        conn.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                "repair_script",
                "REPARACION BODEGA APPS 15-17",
                f"Salidas bodega Apps {APPS} ({FECHA_ESPERADA}) · CC variedad · pool {CC_BODEGA}",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        print(f"OK — {len(inserts)} salida(s) insertadas.")
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
