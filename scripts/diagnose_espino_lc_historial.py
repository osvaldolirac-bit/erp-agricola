#!/usr/bin/env python3
"""Diagnóstico Libro de Campo vs bodega El Espino (fechas / sectores).

Uso:
  python3 scripts/diagnose_espino_lc_historial.py /path/erp_espino.db
  python3 scripts/diagnose_espino_lc_historial.py /path/erp_espino.db --fecha 2026-09-26
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

CC_BODEGA = "EL ESPINO"
SECTORES_LC = (
    "EL ESPINO",
    "CEREZOS",
    "ROYAL DOWN",
    "SWEET ARYANA",
    "SANTINA",
)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    fecha = None
    for i, a in enumerate(sys.argv[2:], start=2):
        if a == "--fecha" and i + 1 < len(sys.argv):
            fecha = sys.argv[i + 1]

    conn = sqlite3.connect(str(db))
    try:
        ph = ",".join("?" * len(SECTORES_LC))
        lc_sql = f"""
            SELECT n_aplicacion, fecha, UPPER(sector), producto, gasto_total
            FROM libro_campo
            WHERE UPPER(sector) IN ({ph})
              AND CAST(n_aplicacion AS INTEGER) < 10000
        """
        params: list = list(SECTORES_LC)
        if fecha:
            lc_sql += " AND (fecha = ? OR fecha LIKE ? OR substr(fecha,1,10) = ?)"
            params.extend([fecha, f"{fecha}%", fecha])
        lc_sql += " ORDER BY fecha DESC, CAST(n_aplicacion AS INTEGER) DESC LIMIT 50"
        lc = conn.execute(lc_sql, params).fetchall()

        mov_sql = """
            SELECT m.id, m.fecha, m.centro_costo, i.producto, m.cantidad, m.tipo
            FROM movimientos m
            JOIN inventario i ON i.id = m.producto_id
            WHERE m.tipo = 'Salida' AND UPPER(m.centro_costo) = ?
        """
        mov_params: list = [CC_BODEGA]
        if fecha:
            mov_sql += " AND (m.fecha = ? OR m.fecha LIKE ? OR substr(m.fecha,1,10) = ?)"
            mov_params.extend([fecha, f"{fecha}%", fecha])
        mov_sql += " ORDER BY m.fecha DESC, m.id DESC LIMIT 50"
        mov = conn.execute(mov_sql, mov_params).fetchall()

        print(f"=== libro_campo (sectores Espino, n_app < 10000) — {len(lc)} filas ===")
        for row in lc:
            print("  LC", row)
        print(f"\n=== movimientos Salida bodega {CC_BODEGA} — {len(mov)} filas ===")
        for row in mov:
            print("  MOV", row)

        ocultos = conn.execute(
            f"""SELECT COUNT(*) FROM libro_campo
                WHERE fecha LIKE ? AND UPPER(sector) NOT IN ({ph})
                  AND CAST(n_aplicacion AS INTEGER) < 10000""",
            [f"{fecha}%" if fecha else "%", *SECTORES_LC],
        ).fetchone()[0]
        if fecha and ocultos:
            print(f"\n⚠ {ocultos} fila(s) LC en {fecha} con sector fuera del ámbito Espino.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
