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
    conn.execute("DELETE FROM facturas WHERE id = ?", (row["ge_id"],))


def _reparar_estado_tesoreria_ge(conn: sqlite3.Connection, apply: bool) -> None:
    """Solo facturas reales que tuvieron duplicado GE: Pendiente si quedaron Pagado sin abono."""
    rows = conn.execute(
        """
        SELECT f.id, f.nro_documento, f.proveedor, f.monto_total, f.monto_pagado
        FROM facturas f
        WHERE f.nro_documento NOT GLOB 'GE-*'
          AND f.nro_documento NOT GLOB '*_P'
          AND f.estado = 'Pagado'
          AND f.monto_total > 0
          AND COALESCE(f.monto_pagado, 0) < f.monto_total - 0.01
          AND EXISTS (
            SELECT 1 FROM facturas g
            WHERE g.nro_documento GLOB 'GE-*'
              AND g.nro_documento NOT GLOB '*_P'
              AND TRIM(g.proveedor) = TRIM(f.nro_documento)
              AND g.fecha_compra = f.fecha_compra
              AND ABS(g.monto_total - f.monto_total) < 500
          )
        ORDER BY f.id
        """
    ).fetchall()
    print(f"Facturas GE duplicado con Pagado sin abono: {len(rows)}")
    for rid, nro, prov, mt, mp in rows:
        saldo = float(mt or 0) - float(mp or 0)
        print(f"  id {rid} {nro} {prov}: Pagado -> Pendiente (saldo ${saldo:,.0f})")
        if apply:
            conn.execute("UPDATE facturas SET estado = 'Pendiente' WHERE id = ?", (rid,))


def _restaurar_factura_pagada(
    conn: sqlite3.Connection, nro: str, apply: bool, *, proveedor: str | None = None
) -> None:
    """Marca Pagado con abono completo (facturas pagadas fuera del flujo Tesorería)."""
    sql = """
        SELECT id, nro_documento, proveedor, monto_total, estado, monto_pagado
        FROM facturas
        WHERE nro_documento = ? AND nro_documento NOT GLOB '*_P'
    """
    params: list = [nro]
    if proveedor:
        sql += " AND proveedor = ?"
        params.append(proveedor)
    row = conn.execute(sql, params).fetchone()
    if not row:
        print(f"Factura {nro}: no encontrada.")
        return
    rid, nro_d, prov, mt, est, mp = row
    if est == "Pagado" and float(mp or 0) >= float(mt or 0) - 0.01:
        print(f"Factura {nro_d} id {rid}: ya Pagado con abono completo.")
        return
    print(f"Factura {nro_d} id {rid} ({prov}): restaurar Pagado ${float(mt or 0):,.0f}")
    if apply:
        conn.execute(
            """
            UPDATE facturas
            SET estado = 'Pagado', monto_pagado = monto_total
            WHERE id = ?
            """,
            (rid,),
        )


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

        print("\n--- Tesorería (solo duplicados GE) ---")
        _reparar_estado_tesoreria_ge(conn, apply=args.apply)

        print("\n--- Factura 42 ventanas (pagada) ---")
        _restaurar_factura_pagada(
            conn,
            "42",
            apply=args.apply,
            proveedor="FRABRICA DE VENTANAS CLAUDIA SILVA GONZALEZ",
        )

        if args.apply:
            conn.commit()
            print("\nCambios aplicados.")
        else:
            print("\nDry-run: sin cambios.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
