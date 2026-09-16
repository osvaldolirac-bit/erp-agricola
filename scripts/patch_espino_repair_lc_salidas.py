#!/usr/bin/env python3
"""Inserta salidas de bodega faltantes según libro_campo (El Espino).

Cuando LC registró consumo pero no se rebajó bodega (p. ej. error previo),
este script crea movimientos Salida por cada línea LC sin par en movimientos.

Uso:
  python3 scripts/patch_espino_repair_lc_salidas.py /root/espino/erp_espino.db
  python3 scripts/patch_espino_repair_lc_salidas.py /root/espino/erp_espino.db --producto ZINC --apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _pid(conn: sqlite3.Connection, prod: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(TRIM(producto))=?",
        (prod.upper().strip(),),
    ).fetchone()
    return int(row[0]) if row else None


def _tiene_par(conn: sqlite3.Connection, pid: int, fecha: str, cant: float, sector: str) -> bool:
    rows = conn.execute(
        """SELECT id, cantidad, centro_costo FROM movimientos
           WHERE producto_id=? AND tipo='Salida' AND fecha=?""",
        (pid, fecha),
    ).fetchall()
    sec_u = (sector or "").strip().upper()
    for _id, c, cc in rows:
        if abs(float(c or 0) - cant) < 1e-4:
            cc_u = (cc or "").strip().upper()
            if sec_u == cc_u or sec_u in cc_u or cc_u in sec_u:
                return True
            if sec_u in ("CEREZOS", "EL ESPINO") and cc_u in ("CEREZOS", "EL ESPINO", "ROYAL DOWN", "SWEET ARYANA", "SANTINA"):
                return True
    return False


def plan(conn: sqlite3.Connection, filtro: str = "") -> list[str]:
    lines: list[str] = []
    q = """SELECT producto, gasto_total, sector, fecha, n_aplicacion
           FROM libro_campo ORDER BY n_aplicacion, id"""
    for prod, gasto, sector, fecha, n_app in conn.execute(q):
        if filtro and filtro.upper() not in str(prod).upper():
            continue
        cant = float(gasto or 0)
        if cant <= 0:
            continue
        pid = _pid(conn, str(prod))
        if pid is None:
            lines.append(f"WARN: sin inventario · App {n_app} · {prod}")
            continue
        if _tiene_par(conn, pid, str(fecha), cant, str(sector or "")):
            continue
        lines.append(
            f"INSERT App {n_app} · {fecha} · {prod} −{cant} → {sector}"
        )
    return lines


def apply(conn: sqlite3.Connection, filtro: str = "") -> int:
    n = 0
    q = """SELECT producto, gasto_total, sector, fecha, n_aplicacion
           FROM libro_campo ORDER BY n_aplicacion, id"""
    for prod, gasto, sector, fecha, n_app in conn.execute(q):
        if filtro and filtro.upper() not in str(prod).upper():
            continue
        cant = float(gasto or 0)
        if cant <= 0:
            continue
        pid = _pid(conn, str(prod))
        if pid is None:
            continue
        if _tiene_par(conn, pid, str(fecha), cant, str(sector or "")):
            continue
        row = conn.execute(
            "SELECT precio_medio, COALESCE(unidad_medida,'L') FROM inventario WHERE id=?",
            (pid,),
        ).fetchone()
        pmp = float(row[0] or 0)
        um = row[1]
        cc = (sector or "Cerezos").strip()
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, "Salida", cant, str(fecha), cc, cant * pmp, um),
        )
        n += 1
    return n


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    filtro = ""
    if "--producto" in sys.argv:
        i = sys.argv.index("--producto")
        filtro = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    do_apply = "--apply" in sys.argv
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")
    conn = sqlite3.connect(str(db))
    try:
        lines = plan(conn, filtro)
        if not lines:
            print("OK — LC y bodega alineados" + (f" (filtro={filtro})" if filtro else ""))
        else:
            print("\n".join(lines))
        if do_apply:
            n = apply(conn, filtro)
            conn.commit()
            print(f"\n=== {n} salida(s) insertada(s) — ejecute patch_espino_sync_inventario_stock.py --apply ===")
        elif lines:
            print("\n=== Dry-run — use --apply ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
