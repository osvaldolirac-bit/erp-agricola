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
    row = conn.execute(
        "SELECT id, producto, precio_medio FROM inventario WHERE id = 115"
    ).fetchone()
    if not row:
        print("NATURAVITAL (id 115) no encontrado; omitiendo.")
        return
    pid, nombre, pmp = row[0], row[1], float(row[2] or 0)
    movs = conn.execute(
        """
        SELECT id, cantidad, valor_imputado, centro_costo
        FROM movimientos WHERE producto_id = ? AND tipo = 'Salida'
        ORDER BY id
        """,
        (pid,),
    ).fetchall()
    if pmp <= 5000:
        print(f"{nombre}: precio_medio {pmp} ya parece razonable; omitiendo.")
        return
    nuevo_pmp = round(pmp / 100.0, 2)
    print(f"{nombre}: precio_medio {pmp} -> {nuevo_pmp} (factor 100)")
    for mid, cant, valor, cc in movs:
        nuevo_valor = round(float(cant) * nuevo_pmp, 2)
        print(f"  mov {mid} {cc}: valor {valor} -> {nuevo_valor}")
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
