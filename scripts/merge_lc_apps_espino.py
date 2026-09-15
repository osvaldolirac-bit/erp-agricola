#!/usr/bin/env python3
"""Funde aplicaciones Libro de Campo El Espino en una sola (n_aplicacion destino).

Actualiza salidas bodega pareadas (misma cantidad/producto/CC) a la fecha unificada.

Uso:
  python3 scripts/merge_lc_apps_espino.py /root/espino/erp_espino.db 8 9 2026-09-14
  python3 scripts/merge_lc_apps_espino.py /root/espino/erp_espino.db 8 9 2026-09-14 --apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _parear_salidas(conn: sqlite3.Connection, app_dest: int, app_src: int, fecha: str) -> list[tuple]:
    """Encuentra movimientos Salida que corresponden a filas LC de app origen."""
    pares: list[tuple] = []
    for n_app in (app_dest, app_src):
        for prod, gasto, sector, lc_fecha in conn.execute(
            """SELECT producto, gasto_total, sector, fecha FROM libro_campo
               WHERE CAST(n_aplicacion AS INTEGER)=? ORDER BY id""",
            (n_app,),
        ):
            qty = float(gasto or 0)
            if qty <= 0:
                continue
            row = conn.execute(
                """SELECT m.id, m.fecha, m.cantidad, m.centro_costo
                   FROM movimientos m
                   JOIN inventario i ON i.id=m.producto_id
                   WHERE m.tipo='Salida'
                     AND UPPER(TRIM(i.producto))=UPPER(TRIM(?))
                     AND ABS(m.cantidad - ?) < 1e-4
                     AND UPPER(TRIM(m.centro_costo))=UPPER(TRIM(?))
                   ORDER BY ABS(julianday(m.fecha) - julianday(?)), m.id
                   LIMIT 1""",
                (prod, qty, sector, lc_fecha),
            ).fetchone()
            if row:
                pares.append((int(row[0]), n_app, prod, qty, str(row[1]), sector))
    return pares


def main() -> None:
    if len(sys.argv) < 5:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    app_dest = int(sys.argv[2])
    app_src = int(sys.argv[3])
    fecha = sys.argv[4]
    do_apply = "--apply" in sys.argv
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")

    conn = sqlite3.connect(str(db))
    try:
        src_rows = conn.execute(
            """SELECT id, n_aplicacion, fecha, sector, producto, gasto_total, n_orden
               FROM libro_campo WHERE CAST(n_aplicacion AS INTEGER)=?
               ORDER BY id""",
            (app_src,),
        ).fetchall()
        if not src_rows:
            raise SystemExit(f"Sin filas LC para app {app_src}")

        dest_meta = conn.execute(
            """SELECT n_orden, sector, t_max, t_min, hr_pct, viento_kmh
               FROM libro_campo WHERE CAST(n_aplicacion AS INTEGER)=?
               ORDER BY id LIMIT 1""",
            (app_dest,),
        ).fetchone()
        if not dest_meta:
            raise SystemExit(f"Sin filas LC para app destino {app_dest}")

        n_orden, sector_ref, t_max, t_min, hr_pct, viento = dest_meta
        dest_count = conn.execute(
            "SELECT COUNT(*) FROM libro_campo WHERE CAST(n_aplicacion AS INTEGER)=?",
            (app_dest,),
        ).fetchone()[0]
        total_lines = dest_count + len(src_rows)

        print(f"=== Fusionar app {app_src} → app {app_dest} · fecha {fecha} ===")
        for r in src_rows:
            print(f"  LC id={r[0]} {r[4]} {r[5]} {r[3]} (era app {r[1]} {r[2]})")

        pares = _parear_salidas(conn, app_dest, app_src, fecha)
        print(f"=== Salidas bodega pareadas ({len(pares)}) ===")
        for mid, n_app, prod, qty, mov_fecha, cc in pares:
            tag = "→ actualizar fecha" if mov_fecha != fecha else "OK"
            print(f"  mov id={mid} app={n_app} {mov_fecha} {cc} {prod} {qty} {tag}")

        if do_apply:
            dest_ids = [
                r[0]
                for r in conn.execute(
                    """SELECT id FROM libro_campo
                       WHERE CAST(n_aplicacion AS INTEGER)=?
                       ORDER BY id""",
                    (app_dest,),
                ).fetchall()
            ]
            all_ids = dest_ids + [r[0] for r in src_rows]
            for i, lid in enumerate(all_ids, start=1):
                conn.execute(
                    """UPDATE libro_campo SET
                       n_aplicacion=?, fecha=?, n_orden=?,
                       n_aplicacion_txt=?, t_max=?, t_min=?, hr_pct=?, viento_kmh=?
                       WHERE id=?""",
                    (
                        app_dest,
                        fecha,
                        n_orden,
                        f"{i} de {total_lines}",
                        t_max,
                        t_min,
                        hr_pct,
                        viento,
                        lid,
                    ),
                )

            mov_ids = sorted({p[0] for p in pares})
            if mov_ids:
                ph = ",".join("?" * len(mov_ids))
                conn.execute(
                    f"UPDATE movimientos SET fecha=? WHERE id IN ({ph})",
                    (fecha, *mov_ids),
                )
            conn.commit()
            print(f"=== Aplicado: app {app_src} fundida en {app_dest} ({total_lines} productos) ===")
        else:
            print("=== Dry-run (use --apply) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
