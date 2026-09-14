#!/usr/bin/env python3
"""Repara salidas LC Espino app 6: elimina duplicados y reimputa a ROYAL DOWN.

Uso en VPS:
  python3 scripts/patch_espino_lc_bodega_rebaje.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Aplicación LC El Espino (2026-09-03, sector ROYAL DOWN).
N_APP = 6
VARIEDAD = "ROYAL DOWN"
FECHA_APP = "2026-09-03"

# Cantidades esperadas por producto (gasto_total app 6).
SALIDAS_APP6: dict[str, float] = {
    "INDAR 2F": 0.5,
    "NUTYRICHELATES ZINC PLUS": 0.5,
    "POLIB": 0.5,
    "ACETAMIPRID 70 WP": 0.25,
    "EVOLUTION FIFTY": 0.5,
}


def _producto_id(conn: sqlite3.Connection, nombre: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(TRIM(producto))=?",
        (nombre.upper().strip(),),
    ).fetchone()
    return int(row[0]) if row else None


def _salidas_producto(conn: sqlite3.Connection, pid: int) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            """SELECT id, cantidad, fecha, centro_costo, tipo
               FROM movimientos
               WHERE producto_id=? AND tipo='Salida'
               ORDER BY id""",
            (pid,),
        ).fetchall()
    )


def _ingresos_pool(conn: sqlite3.Connection, pid: int) -> float:
    ccs = ("CEREZOS", "CEREZOS", "EL ESPINO")  # upper match below
    row = conn.execute(
        """SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
           WHERE producto_id=? AND tipo='Ingreso'
             AND UPPER(centro_costo) IN ('CEREZOS','CEREZOS','EL ESPINO')""",
        (pid,),
    ).fetchone()
    return float(row[0] or 0)


def _sync_inventario_stock(conn: sqlite3.Connection, pid: int) -> float:
    """Ajusta inventario.stock cuando no hay kardex ingreso (pool bodega)."""
    inv = conn.execute("SELECT COALESCE(stock, 0) FROM inventario WHERE id=?", (pid,)).fetchone()
    stock_inv = float(inv[0] or 0) if inv else 0.0
    ing = _ingresos_pool(conn, pid)
    if ing > 1e-9:
        return stock_inv
    sal = conn.execute(
        "SELECT COALESCE(SUM(cantidad), 0) FROM movimientos WHERE producto_id=? AND tipo='Salida'",
        (pid,),
    ).fetchone()
    sal_total = float(sal[0] or 0)
    # Stock inicial implícito = stock_inv actual + salidas (si nunca se rebajó inventario).
    # Tras fix de código, stock = max(stock_base - salidas, 0).
    # Aquí recalculamos desde stock actual + salidas duplicadas eliminadas externamente.
    return stock_inv


def plan(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    dup_ids: list[int] = []

    for prod, cant in SALIDAS_APP6.items():
        pid = _producto_id(conn, prod)
        if pid is None:
            lines.append(f"WARN: producto no encontrado: {prod}")
            continue
        salidas = _salidas_producto(conn, pid)
        matching = [
            s
            for s in salidas
            if abs(float(s["cantidad"]) - cant) < 1e-6
            and str(s["fecha"]) in (FECHA_APP, "2026-09-14")
        ]
        if len(matching) >= 2:
            # Conservar la más antigua (fecha app); eliminar las posteriores.
            keep = min(matching, key=lambda s: int(s["id"]))
            for s in matching:
                if int(s["id"]) != int(keep["id"]):
                    dup_ids.append(int(s["id"]))
                    lines.append(f"DELETE duplicado id={s['id']} {prod} {s['fecha']} cc={s['centro_costo']}")
            lines.append(f"KEEP id={keep['id']} {prod} → cc={VARIEDAD}")
        elif len(matching) == 1:
            s = matching[0]
            lines.append(f"UPDATE id={s['id']} {prod} cc={s['centro_costo']} → {VARIEDAD}")
        else:
            lines.append(f"WARN: sin salida esperada para {prod} ({cant})")

    if dup_ids:
        lines.insert(0, f"Duplicados a eliminar: {sorted(set(dup_ids))}")
    return lines


def apply(conn: sqlite3.Connection) -> None:
    for prod, cant in SALIDAS_APP6.items():
        pid = _producto_id(conn, prod)
        if pid is None:
            continue
        salidas = _salidas_producto(conn, pid)
        matching = [
            s
            for s in salidas
            if abs(float(s["cantidad"]) - cant) < 1e-6
            and str(s["fecha"]) in (FECHA_APP, "2026-09-14")
        ]
        if not matching:
            continue
        keep = min(matching, key=lambda s: int(s["id"]))
        for s in matching:
            if int(s["id"]) != int(keep["id"]):
                conn.execute("DELETE FROM movimientos WHERE id=?", (int(s["id"]),))
        conn.execute(
            "UPDATE movimientos SET centro_costo=? WHERE id=?",
            (VARIEDAD, int(keep["id"])),
        )
        # inventario.stock no se altera: el rebaje se refleja vía movimientos (Salida).


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db_path = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    if not db_path.is_file():
        raise SystemExit(f"No existe: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        print(f"=== Plan rebaje LC app {N_APP} ({VARIEDAD}) ===")
        for line in plan(conn):
            print(line)
        if do_apply:
            apply(conn)
            conn.commit()
            print("=== Aplicado ===")
        else:
            print("=== Dry-run (use --apply para escribir) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
