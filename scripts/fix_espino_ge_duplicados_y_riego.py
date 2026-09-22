#!/usr/bin/env python3
"""Limpia GE-* duplicados en Compras Espino y corrige PMP NATURAVITAL (riego).

Uso:
  python3 scripts/fix_espino_ge_duplicados_y_riego.py --db /root/espino/erp_espino.db --dry-run
  python3 scripts/fix_espino_ge_duplicados_y_riego.py --db /root/espino/erp_espino.db --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def _ge_duplicados(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            """
            SELECT g.id AS ge_id, g.nro_documento AS ge_nro, g.proveedor AS ge_prov,
                   g.monto_total AS ge_monto, g.fecha_compra, g.estado AS ge_estado,
                   f.id AS real_id, f.nro_documento AS real_nro, f.proveedor AS real_prov,
                   f.estado AS real_estado
            FROM facturas g
            INNER JOIN facturas f
              ON f.nro_documento NOT GLOB 'GE-*'
             AND f.nro_documento NOT LIKE '%\\_P' ESCAPE '\\'
             AND TRIM(f.nro_documento) = TRIM(g.proveedor)
             AND f.fecha_compra = g.fecha_compra
             AND ABS(f.monto_total - g.monto_total) < 500
            WHERE g.nro_documento GLOB 'GE-*'
              AND g.nro_documento NOT LIKE '%\\_P' ESCAPE '\\'
            ORDER BY g.id
            """
        )
    )


def _migrar_ge(conn: sqlite3.Connection, row: sqlite3.Row, apply: bool) -> None:
    ge_nro = row["ge_nro"]
    ge_prov = row["ge_prov"]
    real_nro = row["real_nro"]
    real_prov = row["real_prov"]
    imps = conn.execute(
        """
        SELECT id, centro_costo, monto_imputado
        FROM facturas
        WHERE nro_documento = ? AND proveedor = ?
        """,
        (f"{ge_nro}_P", ge_prov),
    ).fetchall()
    print(f"  GE {ge_nro} (id {row['ge_id']}) -> real {real_nro} ({real_prov})")
    print(f"    imputaciones _P: {len(imps)}")
    if not apply:
        return
    for imp in imps:
        conn.execute(
            """
            UPDATE facturas
            SET nro_documento = ?, proveedor = ?
            WHERE id = ?
            """,
            (f"{real_nro}_P", real_prov, imp[0]),
        )
    if row["ge_estado"] == "Pagado" and row["real_estado"] != "Pagado":
        conn.execute(
            "UPDATE facturas SET estado = 'Pagado' WHERE id = ?",
            (row["real_id"],),
        )
    conn.execute("DELETE FROM facturas WHERE id = ?", (row["ge_id"],))


def _fix_naturavital(conn: sqlite3.Connection, apply: bool) -> None:
    """Recalcula PMP NATURAVITAL desde compras Tattersall y kardex de apertura."""
    row = conn.execute(
        "SELECT id, producto, precio_medio, COALESCE(unidad_medida, 'lt') "
        "FROM inventario WHERE UPPER(producto) LIKE '%NATUR%VITAL%'"
    ).fetchone()
    if not row:
        print("NATURAVITAL no encontrado; omitiendo.")
        return
    pid, nombre, pmp_actual, um = row[0], row[1], float(row[2] or 0), row[3]

    compras = conn.execute(
        """
        SELECT COALESCE(SUM(monto_total), 0)
        FROM facturas
        WHERE nro_documento NOT GLOB '*_P'
          AND UPPER(TRIM(concepto)) LIKE '%NATUR%VITAL%'
          AND proveedor LIKE '%TATTERSALL%'
        """
    ).fetchone()[0]
    total_compras = float(compras or 0)
    if total_compras <= 0:
        print(f"{nombre}: sin compras Tattersall de referencia; omitiendo.")
        return

    ing_qty = conn.execute(
        "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Ingreso'",
        (pid,),
    ).fetchone()[0]
    sal_qty = conn.execute(
        "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
        (pid,),
    ).fetchone()[0]
    qty_stock = float(ing_qty or 0)
    if qty_stock <= 0:
        qty_stock = float(sal_qty or 0)
    if qty_stock <= 0:
        qty_stock = float(
            conn.execute("SELECT COALESCE(stock, 0) FROM inventario WHERE id=?", (pid,)).fetchone()[0]
            or 0
        )
    if qty_stock <= 0:
        print(f"{nombre}: no se pudo inferir litros de stock; omitiendo.")
        return

    nuevo_pmp = round(total_compras / qty_stock, 4)
    print(
        f"{nombre}: PMP {pmp_actual} -> {nuevo_pmp} "
        f"(${total_compras:,.0f} / {qty_stock} {um})"
    )

    if float(ing_qty or 0) <= 0:
        print(f"  ingreso apertura kardex: {qty_stock} {um} = ${total_compras:,.0f}")
        if apply:
            conn.execute(
                """
                INSERT INTO movimientos
                (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
                VALUES (?, 'Ingreso', ?, '2026-09-21', 'Cerezos', ?, ?)
                """,
                (pid, qty_stock, total_compras, um),
            )

    movs = conn.execute(
        """
        SELECT id, cantidad, valor_imputado, centro_costo
        FROM movimientos WHERE producto_id = ? AND tipo = 'Salida'
        ORDER BY id
        """,
        (pid,),
    ).fetchall()
    for mid, cant, valor, cc in movs:
        nuevo_valor = round(float(cant) * nuevo_pmp, 2)
        print(f"  salida {mid} {cc}: ${valor:,.0f} -> ${nuevo_valor:,.0f}")
        if apply:
            conn.execute(
                "UPDATE movimientos SET valor_imputado = ? WHERE id = ?",
                (nuevo_valor, mid),
            )
    if apply:
        conn.execute(
            "UPDATE inventario SET precio_medio = ? WHERE id = ?",
            (nuevo_pmp, pid),
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Ruta erp_espino.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.apply == args.dry_run:
        ap.error("Indique --apply o --dry-run")

    db = Path(args.db)
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")

    if args.apply:
        bak = db.with_suffix(
            f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        shutil.copy2(db, bak)
        print(f"Respaldo: {bak}")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        dups = _ge_duplicados(conn)
        print(f"GE duplicados encontrados: {len(dups)}")
        for row in dups:
            _migrar_ge(conn, row, apply=args.apply)

        print("\n--- NATURAVITAL riego ---")
        _fix_naturavital(conn, apply=args.apply)

        if args.apply:
            conn.commit()
            print("\nCambios aplicados.")
        else:
            print("\nDry-run: sin cambios.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
