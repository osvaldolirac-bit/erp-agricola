"""Emparejamiento Libro de Campo ↔ salidas bodega (La Concepción)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import sqlite3

QTY_TOL = 1e-4
DEFAULT_VENTANA_DIAS = 14

# Salidas ya ligadas a una línea LC no cuentan como duplicado de otra aplicación.
_SQL_EXCL_MOV_VINCULADO = (
    " AND id NOT IN (SELECT movimiento_id FROM libro_campo WHERE movimiento_id IS NOT NULL)"
)


def ensure_movimiento_id_column(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(libro_campo)").fetchall()}
    if "movimiento_id" not in cols:
        try:
            conn.execute("ALTER TABLE libro_campo ADD COLUMN movimiento_id INTEGER")
        except sqlite3.OperationalError:
            pass


def parse_fecha_iso(raw: str | None) -> date | None:
    s = str(raw or "").strip()[:10]
    if not s or s == "—":
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def fechas_en_ventana(fecha_a: str | None, fecha_b: str | None, ventana_dias: int) -> bool:
    da = parse_fecha_iso(fecha_a)
    db = parse_fecha_iso(fecha_b)
    if da is None or db is None:
        return str(fecha_a or "").strip()[:10] == str(fecha_b or "").strip()[:10]
    return abs((da - db).days) <= max(1, int(ventana_dias))


def sector_coincide(sector: str, centro_costo: str, cuarteles: set[str] | None = None) -> bool:
    sec_u = (sector or "").strip().upper()
    cc_u = (centro_costo or "").strip().upper()
    if not sec_u or not cc_u:
        return False
    if sec_u == cc_u:
        return True
    if cuarteles and sec_u in cuarteles and cc_u in cuarteles:
        return sec_u == cc_u
    return sec_u in cc_u or cc_u in sec_u


def cantidades_coinciden(a: float, b: float, tol: float = QTY_TOL) -> bool:
    return abs(float(a or 0) - float(b or 0)) <= tol


def lc_linea_coincide_movimiento(
    lc: dict[str, Any],
    mov: dict[str, Any],
    *,
    ventana_dias: int = DEFAULT_VENTANA_DIAS,
    cuarteles: set[str] | None = None,
) -> bool:
    if str(mov.get("tipo") or "").strip().lower().startswith("sal") is False:
        return False
    prod_lc = str(lc.get("producto") or "").strip().upper()
    prod_mov = str(mov.get("producto") or "").strip().upper()
    if prod_lc != prod_mov:
        return False
    if not cantidades_coinciden(lc.get("gasto") or lc.get("gasto_total"), mov.get("cantidad")):
        return False
    if not sector_coincide(str(lc.get("sector") or ""), str(mov.get("centro_costo") or ""), cuarteles):
        return False
    return fechas_en_ventana(str(lc.get("fecha") or ""), str(mov.get("fecha") or ""), ventana_dias)


def _lc_rows(conn: sqlite3.Connection, fi: str, ff: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, n_aplicacion, fecha, sector, producto, gasto_total
           FROM libro_campo
           WHERE COALESCE(gasto_total, 0) > 0
             AND fecha BETWEEN ? AND ?
           ORDER BY fecha, CAST(n_aplicacion AS INTEGER), id""",
        (fi, ff),
    ).fetchall()
    return [
        {
            "lc_id": int(r[0]),
            "n_app": int(r[1] or 0),
            "fecha": str(r[2] or "")[:10],
            "sector": str(r[3] or "").strip().upper(),
            "producto": str(r[4] or "").strip(),
            "gasto": float(r[5] or 0),
        }
        for r in rows
    ]


def _mov_salidas(conn: sqlite3.Connection, fi: str, ff: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT m.id, m.fecha, m.cantidad, m.centro_costo, m.tipo, i.producto, m.producto_id
           FROM movimientos m
           JOIN inventario i ON i.id = m.producto_id
           WHERE m.tipo = 'Salida' AND m.fecha BETWEEN ? AND ?
           ORDER BY m.fecha, m.id""",
        (fi, ff),
    ).fetchall()
    return [
        {
            "mov_id": int(r[0]),
            "fecha": str(r[1] or "")[:10],
            "cantidad": float(r[2] or 0),
            "centro_costo": str(r[3] or "").strip().upper(),
            "tipo": str(r[4] or ""),
            "producto": str(r[5] or "").strip(),
            "producto_id": int(r[6]),
        }
        for r in rows
    ]


def emparejar_lc_movimientos(
    lc_rows: list[dict[str, Any]],
    mov_rows: list[dict[str, Any]],
    *,
    ventana_dias: int = DEFAULT_VENTANA_DIAS,
    cuarteles: set[str] | None = None,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedy 1:1 — prioriza misma fecha, luego menor distancia en días."""
    lc_rest = [dict(x) for x in lc_rows]
    mov_rest = [dict(x) for x in mov_rows]
    pares: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def score(lc: dict, mov: dict) -> tuple[int, int]:
        same_day = 0 if str(lc["fecha"]) == str(mov["fecha"]) else 1
        da = parse_fecha_iso(lc["fecha"])
        db = parse_fecha_iso(mov["fecha"])
        dist = abs((da - db).days) if da and db else 999
        return (same_day, dist)

    while lc_rest and mov_rest:
        best_sc: tuple[int, int] | None = None
        bi = bj = -1
        for i, lc in enumerate(lc_rest):
            for j, mov in enumerate(mov_rest):
                if not lc_linea_coincide_movimiento(
                    lc, mov, ventana_dias=ventana_dias, cuarteles=cuarteles
                ):
                    continue
                sc = score(lc, mov)
                if best_sc is None or sc < best_sc:
                    best_sc = sc
                    bi, bj = i, j
        if best_sc is None:
            break
        lc_pick = lc_rest.pop(bi)
        mov_pick = mov_rest.pop(bj)
        pares.append((lc_pick, mov_pick))

    return pares, lc_rest, mov_rest


def listar_lc_sin_salida_bodega(
    conn: sqlite3.Connection,
    fi: date,
    ff: date,
    *,
    ventana_dias: int = DEFAULT_VENTANA_DIAS,
    cuarteles: set[str] | None = None,
) -> list[dict[str, Any]]:
    pad = timedelta(days=max(1, ventana_dias))
    fi_s = (fi - pad).isoformat()
    ff_s = (ff + pad).isoformat()
    lc_rows = _lc_rows(conn, fi.isoformat(), ff.isoformat())
    mov_rows = _mov_salidas(conn, fi_s, ff_s)
    _, lc_sin, _ = emparejar_lc_movimientos(
        lc_rows, mov_rows, ventana_dias=ventana_dias, cuarteles=cuarteles
    )
    return lc_sin


def insertar_salida_desde_lc(
    conn: sqlite3.Connection,
    lc: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Crea movimiento Salida y descuenta stock si hay inventario."""
    prod = str(lc.get("producto") or "").strip()
    row = conn.execute(
        "SELECT id, precio_medio, COALESCE(unidad_medida, 'kg'), COALESCE(stock, 0) FROM inventario WHERE UPPER(producto)=?",
        (prod.upper(),),
    ).fetchone()
    if not row:
        return {"ok": False, "reason": "sin_inventario", "lc": lc}
    pid, pmp, um, stock = int(row[0]), float(row[1] or 0), str(row[2]), float(row[3] or 0)
    cant = float(lc.get("gasto") or 0)
    cc = str(lc.get("sector") or "").strip().upper()
    fecha = str(lc.get("fecha") or "")[:10]
    if cant <= 0 or not cc:
        return {"ok": False, "reason": "datos_invalidos", "lc": lc}

    dup = conn.execute(
        f"""SELECT id FROM movimientos
           WHERE producto_id=? AND tipo='Salida' AND centro_costo=? AND ABS(cantidad - ?) < ?
             AND fecha BETWEEN date(?, '-14 day') AND date(?, '+14 day')
             {_SQL_EXCL_MOV_VINCULADO}""",
        (pid, cc, cant, QTY_TOL, fecha, fecha),
    ).fetchone()
    if dup:
        return {"ok": True, "skipped": True, "mov_id": int(dup[0]), "lc": lc}

    if stock + QTY_TOL < cant:
        dup_prev = conn.execute(
            f"""SELECT id FROM movimientos
               WHERE producto_id=? AND tipo='Salida' AND centro_costo=? AND ABS(cantidad - ?) < ?
               {_SQL_EXCL_MOV_VINCULADO}
               ORDER BY id DESC LIMIT 1""",
            (pid, cc, cant, QTY_TOL),
        ).fetchone()
        if dup_prev:
            return {"ok": True, "skipped": True, "mov_id": int(dup_prev[0]), "lc": lc}
        return {"ok": False, "reason": "stock_insuficiente", "stock": stock, "lc": lc}

    if dry_run:
        return {"ok": True, "dry_run": True, "producto_id": pid, "cantidad": cant, "fecha": fecha, "cc": cc, "lc": lc}

    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (pid, "Salida", cant, fecha, cc, cant * pmp, um),
    )
    cur = conn.execute(
        "UPDATE inventario SET stock = stock - ? WHERE id = ? AND stock >= ?",
        (cant, pid, cant),
    )
    if cur.rowcount != 1:
        conn.rollback()
        return {"ok": False, "reason": "stock_race", "lc": lc}
    mov_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return {"ok": True, "mov_id": mov_id, "producto_id": pid, "lc": lc}


def lc_dict_desde_item_libro(
    item: dict[str, Any],
    *,
    fecha,
    sector: str,
) -> dict[str, Any]:
    fe = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")[:10]
    return {
        "producto": str(item.get("producto") or "").strip(),
        "gasto": float(item.get("gasto_total") or 0),
        "sector": str(sector or "").strip().upper(),
        "fecha": fe,
    }


def lc_dict_desde_linea_libro(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "producto": str(row.get("producto") or "").strip(),
        "gasto": float(row.get("gasto_total") or 0),
        "sector": str(row.get("sector") or "").strip().upper(),
        "fecha": str(row.get("fecha") or "")[:10],
    }
    if row.get("movimiento_id") is not None:
        try:
            out["movimiento_id"] = int(row["movimiento_id"])
        except (TypeError, ValueError):
            pass
    return out


def vincular_movimiento_linea_libro(conn: sqlite3.Connection, linea_id: int, mov_id: int) -> None:
    ensure_movimiento_id_column(conn)
    conn.execute(
        "UPDATE libro_campo SET movimiento_id=? WHERE id=?",
        (int(mov_id), int(linea_id)),
    )


def mensaje_error_salida_lc(demo, res: dict[str, Any]) -> str:
    reason = res.get("reason") or ""
    lc = res.get("lc") or {}
    prod = lc.get("producto") or "producto"
    if reason == "sin_inventario":
        return f"«{prod}» no está en inventario bodega LC."
    if reason == "stock_insuficiente":
        st = float(res.get("stock") or 0)
        return (
            f"Stock bodega insuficiente para «{prod}» "
            f"(disponible {demo.f_cantidad(st)})."
        )
    if reason == "datos_invalidos":
        return f"Cantidad o cuartel inválido para «{prod}»."
    if reason == "stock_race":
        return f"No se pudo descontar «{prod}» (stock cambió al guardar). Reintente."
    return f"No se pudo rebajar bodega para «{prod}»."


def _buscar_mov_salida_revertir(
    conn: sqlite3.Connection,
    pid: int,
    cant: float,
    cc: str,
    fecha: str,
    *,
    excluir_mov_ids: set[int] | None = None,
    ventana_dias: int = 14,
) -> int | None:
    excl = sorted(excluir_mov_ids or ())
    excl_sql = ""
    excl_params: list = []
    if excl:
        excl_sql = f" AND id NOT IN ({','.join('?' * len(excl))})"
        excl_params = list(excl)

    def _query(with_window: bool) -> int | None:
        window_sql = ""
        window_params: list = []
        if with_window:
            window_sql = " AND fecha BETWEEN date(?, ?) AND date(?, ?)"
            window_params = [fecha, f"-{ventana_dias} day", fecha, f"+{ventana_dias} day"]
        row = conn.execute(
            f"""SELECT id FROM movimientos
               WHERE producto_id=? AND tipo='Salida' AND centro_costo=? AND ABS(cantidad - ?) < ?
               {window_sql}{excl_sql}
               ORDER BY ABS(julianday(fecha) - julianday(?)) ASC, id DESC
               LIMIT 1""",
            [pid, cc, cant, QTY_TOL, *window_params, *excl_params, fecha],
        ).fetchone()
        return int(row[0]) if row else None

    mov_id = _query(True)
    if mov_id is None:
        mov_id = _query(False)
    return mov_id


def revertir_salida_desde_lc(
    conn: sqlite3.Connection,
    lc: dict[str, Any],
    *,
    excluir_mov_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Devuelve stock si existe salida bodega emparejable (reabrir / eliminar aplicación)."""
    prod = str(lc.get("producto") or "").strip()
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(producto)=?",
        (prod.upper(),),
    ).fetchone()
    if not row:
        return {"ok": True, "skipped": True, "reason": "sin_inventario", "lc": lc}
    pid = int(row[0])
    cant = float(lc.get("gasto") or lc.get("gasto_total") or 0)
    cc = str(lc.get("sector") or "").strip().upper()
    fecha = str(lc.get("fecha") or "")[:10]
    if cant <= 0:
        return {"ok": True, "skipped": True, "reason": "datos_invalidos", "lc": lc}
    mov_id = None
    ligado = lc.get("movimiento_id")
    if ligado is not None:
        try:
            ligado = int(ligado)
        except (TypeError, ValueError):
            ligado = None
    if ligado and ligado not in (excluir_mov_ids or ()):
        ok_mov = conn.execute(
            "SELECT id FROM movimientos WHERE id=? AND tipo='Salida' AND producto_id=?",
            (ligado, pid),
        ).fetchone()
        if ok_mov:
            mov_id = ligado
    if not mov_id:
        mov_id = _buscar_mov_salida_revertir(
            conn, pid, cant, cc, fecha, excluir_mov_ids=excluir_mov_ids
        )
    if not mov_id:
        return {"ok": True, "skipped": True, "reason": "sin_movimiento", "lc": lc}
    conn.execute("DELETE FROM movimientos WHERE id=?", (mov_id,))
    conn.execute(
        "UPDATE inventario SET stock = COALESCE(stock, 0) + ? WHERE id=?",
        (cant, pid),
    )
    return {"ok": True, "mov_id": mov_id, "lc": lc}


def revertir_salidas_lineas_libro(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Revierte salidas bodega para cada línea LC (1:1, sin reutilizar el mismo movimiento)."""
    usados: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        lc = lc_dict_desde_linea_libro(row)
        res = revertir_salida_desde_lc(conn, lc, excluir_mov_ids=usados)
        if res.get("mov_id"):
            usados.add(int(res["mov_id"]))
        out.append(res)
    return out
