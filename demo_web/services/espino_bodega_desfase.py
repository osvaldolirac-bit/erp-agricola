"""Vínculo Libro Espino ↔ movimientos bodega CC EL ESPINO."""
from __future__ import annotations

from typing import Any

import sqlite3

from demo_web.services.native import espino_bodega

QTY_TOL = 1e-4


def _cc_bodega_in(col: str = "centro_costo") -> tuple[str, tuple[str, ...]]:
    return espino_bodega._cc_bodega_in(col)


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
    cc_sql, cc_params = _cc_bodega_in()
    if ligado and ligado not in excl:
        ok = conn.execute(
            f"SELECT id FROM movimientos WHERE id=? AND tipo='Salida' AND producto_id=? AND {cc_sql}",
            (ligado, pid, *cc_params),
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
               WHERE producto_id=? AND tipo='Salida' AND {cc_sql}
                 AND ABS(cantidad - ?) < ? AND fecha=?
               {excl_sql}
               ORDER BY id DESC LIMIT 1""",
            [pid, *cc_params, cant, QTY_TOL, fecha, *excl_params],
        ).fetchone()
        mov_id = int(q[0]) if q else None

    if not mov_id:
        return {"ok": True, "skipped": True, "reason": "sin_movimiento", "producto": prod}

    conn.execute("DELETE FROM movimientos WHERE id=?", (mov_id,))
    espino_bodega._sync_inventario_stock(conn, pid)
    return {"ok": True, "mov_id": mov_id, "producto": prod}


def excluir_desfase_ligado(
    conn: sqlite3.Connection,
    lc_rows: list[dict],
    bod_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Saca del desfase las líneas ya ligadas a una salida de bodega.

    El cuartel del libro es la variedad y la salida queda en EL ESPINO;
    el cruce por nombre de cuartel las marca como desfase aunque el vínculo exista.
    """
    try:
        links = conn.execute(
            """SELECT l.n_aplicacion,
                      UPPER(TRIM(COALESCE(l.producto, ''))) AS prod,
                      SUBSTR(COALESCE(m.fecha, ''), 1, 10) AS fecha,
                      UPPER(TRIM(COALESCE(i.producto, ''))) AS mprod,
                      UPPER(TRIM(COALESCE(m.centro_costo, ''))) AS cc
               FROM libro_campo l
               JOIN movimientos m ON m.id = l.movimiento_id
               JOIN inventario i ON i.id = m.producto_id
               WHERE l.movimiento_id IS NOT NULL"""
        ).fetchall()
    except sqlite3.OperationalError:
        return lc_rows, bod_rows
    lc_keys = {(int(r[0]), r[1]) for r in links if r[0] is not None}
    bod_keys = {(r[2], r[3], r[4]) for r in links}

    def _keep_lc(row: dict) -> bool:
        try:
            n_app = int(row.get("N° APP") or row.get("n_aplicacion") or 0)
        except (TypeError, ValueError):
            return True
        prod = str(row.get("PRODUCTO") or row.get("producto") or "").strip().upper()
        return (n_app, prod) not in lc_keys

    def _keep_bod(row: dict) -> bool:
        fecha = str(row.get("FECHA") or row.get("fecha") or "")[:10]
        prod = str(row.get("PRODUCTO") or row.get("producto") or "").strip().upper()
        cc = str(row.get("CUARTEL") or row.get("centro_costo") or "").strip().upper()
        return (fecha, prod, cc) not in bod_keys

    return [r for r in lc_rows if _keep_lc(r)], [r for r in bod_rows if _keep_bod(r)]


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
