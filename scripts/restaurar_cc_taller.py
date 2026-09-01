#!/usr/bin/env python3
"""Restaura un centro de costo y sus compras imputadas desde comercial-demo a taller-demo."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/riomaipo/data/comercial_demo.db")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "/root/riomaipo/data/taller_demo.db")
CC_NOMBRE = (sys.argv[3] if len(sys.argv) > 3 else "FYVT-60").strip()


def _insert_row(cur: sqlite3.Cursor, table: str, row: sqlite3.Row) -> None:
    data = dict(row)
    rid = data.pop("id")
    cols = list(data.keys())
    cur.execute(
        f"DELETE FROM [{table}] WHERE id=?",
        (rid,),
    )
    cur.execute(
        f"INSERT INTO [{table}] (id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
        [rid, *[data[c] for c in cols]],
    )


def _sync_seq(cur: sqlite3.Cursor, table: str) -> None:
    max_id = cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM [{table}]").fetchone()[0]
    cur.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
    if max_id:
        cur.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, max_id))


def main() -> None:
    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(DST)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys = OFF")
    cur = dst.cursor()

    cc = src.execute(
        "SELECT * FROM centros_costo WHERE lower(nombre)=lower(?)",
        (CC_NOMBRE,),
    ).fetchone()
    if not cc:
        raise SystemExit(f"CC no encontrado en origen: {CC_NOMBRE}")

    cc_id = int(cc["id"])
    _insert_row(cur, "centros_costo", cc)

    factura_ids = [
        int(r["factura_id"])
        for r in src.execute(
            "SELECT DISTINCT factura_id FROM factura_compra_cc WHERE centro_costo_id=?",
            (cc_id,),
        ).fetchall()
    ]

    proveedor_ids: set[int] = set()
    producto_ids: set[int] = set()

    for fid in factura_ids:
        fac = src.execute("SELECT * FROM facturas_compra WHERE id=?", (fid,)).fetchone()
        if not fac:
            continue
        if fac["proveedor_id"]:
            proveedor_ids.add(int(fac["proveedor_id"]))
        for it in src.execute(
            "SELECT * FROM factura_compra_items WHERE factura_id=?", (fid,)
        ).fetchall():
            if it["producto_id"]:
                producto_ids.add(int(it["producto_id"]))

    for pid in sorted(proveedor_ids):
        row = src.execute("SELECT * FROM proveedores WHERE id=?", (pid,)).fetchone()
        if row:
            _insert_row(cur, "proveedores", row)

    for pid in sorted(producto_ids):
        row = src.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
        if row:
            _insert_row(cur, "productos", row)

    for fid in factura_ids:
        fac = src.execute("SELECT * FROM facturas_compra WHERE id=?", (fid,)).fetchone()
        if fac:
            _insert_row(cur, "facturas_compra", fac)
        for it in src.execute(
            "SELECT * FROM factura_compra_items WHERE factura_id=?", (fid,)
        ).fetchall():
            _insert_row(cur, "factura_compra_items", it)
        for pay in src.execute(
            "SELECT * FROM pagos_compra WHERE factura_id=?", (fid,)
        ).fetchall():
            _insert_row(cur, "pagos_compra", pay)
        for imp in src.execute(
            "SELECT * FROM factura_compra_cc WHERE factura_id=?", (fid,)
        ).fetchall():
            _insert_row(cur, "factura_compra_cc", imp)

    for table in (
        "centros_costo",
        "proveedores",
        "productos",
        "facturas_compra",
        "factura_compra_items",
        "factura_compra_cc",
        "pagos_compra",
    ):
        _sync_seq(cur, table)

    dst.execute("PRAGMA foreign_keys = ON")
    dst.commit()
    src.close()
    dst.close()
    print(f"OK · {CC_NOMBRE} restaurado en {DST} ({len(factura_ids)} factura(s))")


if __name__ == "__main__":
    main()
