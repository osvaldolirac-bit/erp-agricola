#!/usr/bin/env python3
"""Audita y reconcilia stock bodega El Espino (kardex vs LC vs inventario).

Detecta productos donde ing − salidas_mov ≠ stock mostrado, o donde libro_campo
registra más consumo que salidas de bodega.

Uso:
  python3 scripts/patch_espino_audit_bodega_stock.py /root/espino/erp_espino.db
  python3 scripts/patch_espino_audit_bodega_stock.py /root/espino/erp_espino.db --producto ZINC
  python3 scripts/patch_espino_audit_bodega_stock.py /root/espino/erp_espino.db --apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

POOL_CCS = ("CEREZOS", "EL ESPINO")


def _ing(conn: sqlite3.Connection, pid: int) -> float:
    ph = ",".join("?" * len(POOL_CCS))
    row = conn.execute(
        f"""SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
            WHERE producto_id=? AND tipo='Ingreso' AND UPPER(centro_costo) IN ({ph})""",
        (pid, *POOL_CCS),
    ).fetchone()
    return float(row[0] or 0)


def _sal(conn: sqlite3.Connection, pid: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
        (pid,),
    ).fetchone()
    return float(row[0] or 0)


def _lc(conn: sqlite3.Connection, prod: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(gasto_total), 0) FROM libro_campo WHERE UPPER(TRIM(producto))=?",
        (prod.upper().strip(),),
    ).fetchone()
    return float(row[0] or 0)


def _lc_detalle(conn: sqlite3.Connection, prod: str) -> list[tuple]:
    return conn.execute(
        """SELECT n_aplicacion, fecha, sector, gasto_total
           FROM libro_campo WHERE UPPER(TRIM(producto))=?
           ORDER BY n_aplicacion, id""",
        (prod.upper().strip(),),
    ).fetchall()


def _sal_detalle(conn: sqlite3.Connection, pid: int) -> list[tuple]:
    return conn.execute(
        """SELECT id, fecha, cantidad, centro_costo
           FROM movimientos WHERE producto_id=? AND tipo='Salida'
           ORDER BY id""",
        (pid,),
    ).fetchall()


def audit(conn: sqlite3.Connection, filtro: str = "") -> list[str]:
    lines: list[str] = []
    q = "SELECT id, producto, COALESCE(stock, 0) FROM inventario ORDER BY producto"
    rows = conn.execute(q).fetchall()
    for pid, prod, inv in rows:
        if filtro and filtro.upper() not in str(prod).upper():
            continue
        pid = int(pid)
        ing, sal, lc = _ing(conn, pid), _sal(conn, pid), _lc(conn, str(prod))
        inv = float(inv or 0)
        if ing > 1e-9:
            esperado = max(ing - sal, 0.0)
        else:
            esperado = inv
        diff_lc = lc - sal
        diff_inv = esperado - inv
        if abs(diff_lc) < 1e-6 and abs(esperado - (ing - sal if ing > 0 else inv)) < 1e-6:
            if ing <= 0 or abs(esperado - inv) < 1e-6:
                continue
        lines.append(f"\n=== {prod} (id={pid}) ===")
        lines.append(f"  ingresos kardex: {ing}")
        lines.append(f"  salidas mov:     {sal}")
        lines.append(f"  LC gasto_total:  {lc}")
        lines.append(f"  inventario.stock:{inv}")
        lines.append(f"  stock esperado:  {esperado}")
        if abs(diff_lc) > 1e-6:
            lines.append(f"  ⚠ LC − mov = {diff_lc:+.4f} (LC usa más/menos que bodega)")
        if ing > 1e-9 and abs(diff_inv) > 1e-6:
            lines.append(f"  ⚠ inventario desfasado: {inv} → {esperado}")
        if abs(diff_lc) > 1e-6:
            lines.append("  Libro de campo:")
            for r in _lc_detalle(conn, str(prod)):
                lines.append(f"    App {r[0]} · {r[1]} · {r[2]} · −{r[3]}")
            lines.append("  Salidas bodega:")
            for r in _sal_detalle(conn, pid):
                lines.append(f"    id={r[0]} · {r[1]} · −{r[2]} · {r[3]}")
    return lines


def apply(conn: sqlite3.Connection, filtro: str = "") -> None:
    for pid, prod, inv in conn.execute(
        "SELECT id, producto, COALESCE(stock, 0) FROM inventario ORDER BY id"
    ):
        if filtro and filtro.upper() not in str(prod).upper():
            continue
        pid = int(pid)
        ing, sal = _ing(conn, pid), _sal(conn, pid)
        if ing > 1e-9:
            nuevo = max(ing - sal, 0.0)
            conn.execute("UPDATE inventario SET stock=? WHERE id=?", (nuevo, pid))


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
        lines = audit(conn, filtro)
        if not lines:
            print("OK — sin desfaces detectados" + (f" (filtro={filtro})" if filtro else ""))
        else:
            print("\n".join(lines))
        if do_apply:
            apply(conn, filtro)
            conn.commit()
            print("\n=== inventario.stock sincronizado con kardex (ing − sal) ===")
        elif lines:
            print("\n=== Dry-run — use --apply para sincronizar inventario.stock ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
