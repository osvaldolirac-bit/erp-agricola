"""Vínculo Libro Espino ↔ movimientos bodega CC EL ESPINO."""
from __future__ import annotations

from typing import Any

import sqlite3

from demo_web.services.native import espino_bodega
from demo_web.services.native.espino_bodega import CC_ESPINO

QTY_TOL = 1e-4


def revertir_salida_linea_espino(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    excluir_mov_ids: set[int] | None = None,
) -> dict[str, Any]:
    prod = str(row.get("producto") or "").strip()
    pid_row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(producto)=?",
        (prod.upper(),),
    ).fetchone()
    if not pid_row:
        return {"ok": True, "skipped": True, "reason": "sin_inventario"}
    pid = int(pid_row[0])
    cant = float(row.get("gasto_total") or 0)
    fecha = str(row.get("fecha") or "")[:10]
    if cant <= 0:
        return {"ok": True, "skipped": True, "reason": "datos_invalidos"}

    mov_id = None
    ligado = row.get("movimiento_id")
    if ligado is not None:
        try:
            ligado = int(ligado)
        except (TypeError, ValueError):
            ligado = None
    excl = excluir_mov_ids or set()
    if ligado and ligado not in excl:
        ok = conn.execute(
            "SELECT id FROM movimientos WHERE id=? AND tipo='Salida' AND producto_id=? AND centro_costo=?",
            (ligado, pid, CC_ESPINO),
        ).fetchone()
        if ok:
            mov_id = ligado

    if not mov_id:
        excl_sql = ""
        excl_params: list = []
        if excl:
            excl_sql = f" AND id NOT IN ({','.join('?' * len(excl))})"
            excl_params = sorted(excl)
        q = conn.execute(
            f"""SELECT id FROM movimientos
               WHERE producto_id=? AND tipo='Salida' AND centro_costo=?
                 AND ABS(cantidad - ?) < ? AND fecha=?
               {excl_sql}
               ORDER BY id DESC LIMIT 1""",
            [pid, CC_ESPINO, cant, QTY_TOL, fecha, *excl_params],
        ).fetchone()
        mov_id = int(q[0]) if q else None

    if not mov_id:
        return {"ok": True, "skipped": True, "reason": "sin_movimiento", "producto": prod}

    conn.execute("DELETE FROM movimientos WHERE id=?", (mov_id,))
    espino_bodega._sync_inventario_stock(conn, pid)
    return {"ok": True, "mov_id": mov_id, "producto": prod}


def revertir_salidas_lineas_espino(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    usados: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        res = revertir_salida_linea_espino(conn, row, excluir_mov_ids=usados)
        if res.get("mov_id"):
            usados.add(int(res["mov_id"]))
        out.append(res)
    return out
