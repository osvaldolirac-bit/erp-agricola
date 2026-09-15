#!/usr/bin/env python3
"""Backfill ingresos kardex bodega El Espino desde detalle real de compras (facturas.concepto).

Las entradas deben coincidir con fecha_compra y cantidad del módulo Compras, no con
estimaciones stock+salidas.

Uso:
  python3 scripts/backfill_kardex_compras_espino.py /root/espino/erp_espino.db
  python3 scripts/backfill_kardex_compras_espino.py /root/espino/erp_espino.db --apply
  python3 scripts/backfill_kardex_compras_espino.py /root/espino/erp_espino.db --apply --purge-synthetic
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_web.services.espino_compras_kardex import match_producto_id, parse_concepto_compra
from demo_web.services.espino_scope import CC_MOVIMIENTOS_BODEGA_ESPINO, centros_costo_bodega_espino

CC_MOV = CC_MOVIMIENTOS_BODEGA_ESPINO
POOL_CCS = tuple(sorted({c.upper() for c in centros_costo_bodega_espino()}))
SYNTHETIC_FECHA = "2026-01-01"


def _pool_ph() -> tuple[str, tuple[str, ...]]:
    return ",".join("?" * len(POOL_CCS)), POOL_CCS


def _tiene_ingreso(conn: sqlite3.Connection, producto_id: int, fecha: str, cant: float) -> bool:
    ph, ccs = _pool_ph()
    row = conn.execute(
        f"""SELECT 1 FROM movimientos
            WHERE producto_id=? AND tipo='Ingreso' AND fecha=?
              AND ABS(cantidad - ?) < 1e-4
              AND UPPER(centro_costo) IN ({ph})
            LIMIT 1""",
        (producto_id, fecha, cant, *ccs),
    ).fetchone()
    return row is not None


def _iter_lineas_compra(conn: sqlite3.Connection):
    for fid, nro, fecha, concepto in conn.execute(
        """SELECT id, nro_documento, fecha_compra, concepto FROM facturas
           WHERE nro_documento NOT LIKE '%_P' AND COALESCE(concepto, '') != ''
           ORDER BY fecha_compra, id"""
    ):
        items = parse_concepto_compra(str(concepto or ""))
        if not items:
            continue
        yield int(fid), str(nro or ""), str(fecha or ""), items


def plan(conn: sqlite3.Connection, *, purge_synthetic: bool) -> list[str]:
    lines: list[str] = []
    if purge_synthetic:
        ph, ccs = _pool_ph()
        n = conn.execute(
            f"""SELECT COUNT(*) FROM movimientos
                WHERE tipo='Ingreso' AND fecha=? AND UPPER(centro_costo) IN ({ph})""",
            (SYNTHETIC_FECHA, *ccs),
        ).fetchone()[0]
        if n:
            lines.append(f"PURGE {n} ingreso(s) sintético(s) fecha={SYNTHETIC_FECHA}")

    for fid, nro, fecha, items in _iter_lineas_compra(conn):
        for item in items:
            pid = match_producto_id(conn, item["producto"])
            qty = float(item["cantidad"])
            if not pid:
                lines.append(f"SKIP sin match inventario: {nro} {fecha} {qty} x {item['producto']}")
                continue
            prod = conn.execute("SELECT producto FROM inventario WHERE id=?", (pid,)).fetchone()[0]
            if _tiene_ingreso(conn, pid, fecha, qty):
                lines.append(f"OK ya existe: {prod} +{qty} {fecha} (factura {nro})")
                continue
            lines.append(f"INSERT: {prod} +{qty} {fecha} ← Compra N° {nro} (factura id={fid})")
    return lines


def apply(conn: sqlite3.Connection, *, purge_synthetic: bool) -> None:
    ph, ccs = _pool_ph()
    if purge_synthetic:
        conn.execute(
            f"""DELETE FROM movimientos
                WHERE tipo='Ingreso' AND fecha=? AND UPPER(centro_costo) IN ({ph})""",
            (SYNTHETIC_FECHA, *ccs),
        )

    touched: set[int] = set()
    for _fid, nro, fecha, items in _iter_lineas_compra(conn):
        for item in items:
            pid = match_producto_id(conn, item["producto"])
            qty = float(item["cantidad"])
            if not pid or _tiene_ingreso(conn, pid, fecha, qty):
                continue
            row = conn.execute(
                "SELECT precio_medio, COALESCE(unidad_medida, 'L') FROM inventario WHERE id=?",
                (pid,),
            ).fetchone()
            pmp, um_inv = float(row[0] or 0), str(row[1] or "L")
            um = item.get("um") or um_inv
            conn.execute(
                """INSERT INTO movimientos
                   (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
                   VALUES (?,?,?,?,?,?,?)""",
                (pid, "Ingreso", qty, fecha, CC_MOV, qty * pmp, um),
            )
            touched.add(pid)

    for pid in touched:
        ing = float(
            conn.execute(
                f"""SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
                    WHERE producto_id=? AND tipo='Ingreso' AND UPPER(centro_costo) IN ({ph})""",
                (pid, *ccs),
            ).fetchone()[0]
            or 0
        )
        sal = float(
            conn.execute(
                "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
                (pid,),
            ).fetchone()[0]
            or 0
        )
        if ing > 1e-9:
            conn.execute(
                "UPDATE inventario SET stock=? WHERE id=?",
                (max(ing - sal, 0.0), pid),
            )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    purge = "--purge-synthetic" in sys.argv
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")
    conn = sqlite3.connect(str(db))
    try:
        for line in plan(conn, purge_synthetic=purge):
            print(line)
        if do_apply:
            apply(conn, purge_synthetic=purge)
            conn.commit()
            print("=== Aplicado ===")
        else:
            print("=== Dry-run (use --apply) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
