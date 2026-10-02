#!/usr/bin/env python3
"""Repara salidas LC Espino: elimina duplicados y reimputa al cuartel/variedad.

Por defecto repara aplicación N°6 (2026-09-03, ROYAL DOWN). Cantidades se leen
desde libro_campo.

Uso en VPS:
  python3 scripts/patch_espino_lc_bodega_rebaje.py /root/espino/erp_espino.db [--apply]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

N_APP = 6


def _salidas_esperadas(conn: sqlite3.Connection) -> tuple[dict[str, tuple[float, str]], str]:
    """producto → (gasto_total, sector/variedad)."""
    rows = conn.execute(
        """SELECT producto, gasto_total, sector, fecha
           FROM libro_campo WHERE n_aplicacion=? ORDER BY id""",
        (N_APP,),
    ).fetchall()
    if not rows:
        raise SystemExit(f"No hay filas libro_campo para n_aplicacion={N_APP}")
    fecha = str(rows[0][3])
    out: dict[str, tuple[float, str]] = {}
    for prod, gasto, sector, _ in rows:
        out[str(prod).strip()] = (float(gasto or 0), str(sector or "").strip())
    return out, fecha


def _producto_id(conn: sqlite3.Connection, nombre: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(TRIM(producto))=?",
        (nombre.upper().strip(),),
    ).fetchone()
    return int(row[0]) if row else None


def _salidas_producto(conn: sqlite3.Connection, pid: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """SELECT id, cantidad, fecha, centro_costo, tipo
               FROM movimientos
               WHERE producto_id=? AND tipo='Salida'
               ORDER BY id""",
            (pid,),
        ).fetchall()
    )


def plan(conn: sqlite3.Connection) -> list[str]:
    esperadas, fecha_app = _salidas_esperadas(conn)
    lines: list[str] = [f"App N°{N_APP} · fecha {fecha_app} · {len(esperadas)} productos"]

    for prod, (cant, variedad) in esperadas.items():
        pid = _producto_id(conn, prod)
        if pid is None:
            lines.append(f"WARN: producto no encontrado: {prod}")
            continue
        salidas = [
            s
            for s in _salidas_producto(conn, pid)
            if abs(float(s["cantidad"]) - cant) < 1e-4
        ]
        if not salidas:
            lines.append(f"INSERT pendiente: {prod} −{cant} → {variedad} (sin salida bodega)")
            continue
        keep = min(salidas, key=lambda s: (str(s["fecha"]) != fecha_app, int(s["id"])))
        for s in salidas:
            if int(s["id"]) == int(keep["id"]):
                cc_old = s["centro_costo"]
                if cc_old != variedad:
                    lines.append(
                        f"UPDATE id={s['id']} {prod} cc={cc_old} → {variedad} ({cant})"
                    )
                else:
                    lines.append(f"OK id={s['id']} {prod} cc={variedad} ({cant})")
            else:
                lines.append(
                    f"DELETE duplicado id={s['id']} {prod} {s['fecha']} cc={s['centro_costo']} ({cant})"
                )
    return lines


def apply(conn: sqlite3.Connection) -> None:
    esperadas, fecha_app = _salidas_esperadas(conn)
    for prod, (cant, variedad) in esperadas.items():
        pid = _producto_id(conn, prod)
        if pid is None:
            continue
        salidas = [
            s
            for s in _salidas_producto(conn, pid)
            if abs(float(s["cantidad"]) - cant) < 1e-4
        ]
        if not salidas:
            row = conn.execute(
                "SELECT precio_medio, COALESCE(unidad_medida,'L') FROM inventario WHERE id=?",
                (pid,),
            ).fetchone()
            pmp = float(row[0] or 0)
            um = row[1]
            conn.execute(
                """INSERT INTO movimientos
                   (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
                   VALUES (?,?,?,?,?,?,?)""",
                (pid, "Salida", cant, fecha_app, variedad, cant * pmp, um),
            )
            continue
        keep = min(salidas, key=lambda s: (str(s["fecha"]) != fecha_app, int(s["id"])))
        for s in salidas:
            if int(s["id"]) != int(keep["id"]):
                conn.execute("DELETE FROM movimientos WHERE id=?", (int(s["id"]),))
        conn.execute(
            "UPDATE movimientos SET centro_costo=?, fecha=? WHERE id=?",
            (variedad, fecha_app, int(keep["id"])),
        )


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
        print("=== Plan rebaje LC Espino ===")
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
