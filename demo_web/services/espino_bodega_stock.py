"""Stock bodega El Espino — una sola fuente de verdad (kardex + sync inventario)."""
from __future__ import annotations

import sqlite3
from typing import Any

from demo_web.services.espino_scope import BODEGA_CC_ESPINO, centros_costo_bodega_espino

CC_INGRESO_CANONICO = BODEGA_CC_ESPINO
_CCS_INGRESO: tuple[str, ...] = tuple(sorted(centros_costo_bodega_espino()))


def _case_pool_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    placeholders = ",".join("?" * len(_CCS_INGRESO))
    return f"""SUM(CASE
        WHEN {prefix}tipo = 'Ingreso'
             AND UPPER(TRIM({prefix}centro_costo)) IN ({placeholders})
        THEN {prefix}cantidad
        WHEN {prefix}tipo = 'Salida' THEN -{prefix}cantidad
        ELSE 0
    END)"""


def stock_inventario(conn: sqlite3.Connection, producto_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(stock, 0) FROM inventario WHERE id=?",
        (int(producto_id),),
    ).fetchone()
    return float(row[0] or 0) if row else 0.0


def stock_disponible_bodega(conn: sqlite3.Connection, producto_id: int) -> float:
    """Saldo usable en bodega Espino: kardex (pool) o inventario manual si es mayor."""
    return max(stock_pool(conn, producto_id), stock_inventario(conn, producto_id))


def stock_disponible_map(conn: sqlite3.Connection) -> dict[int, float]:
    pool = stock_pool_map(conn)
    out = dict(pool)
    for pid, inv in conn.execute("SELECT id, COALESCE(stock, 0) FROM inventario"):
        i = int(pid)
        v = max(out.get(i, 0.0), float(inv or 0))
        if v > 1e-12:
            out[i] = v
    return out


def materializar_ajuste_manual_inventario(
    conn: sqlite3.Connection,
    producto_id: int,
    *,
    fecha: str,
) -> float:
    """Si inventario > pool, crea ingreso kardex por la diferencia (ajuste manual operativo)."""
    pool = stock_pool(conn, producto_id)
    inv = stock_inventario(conn, producto_id)
    delta = inv - pool
    if delta <= 1e-6:
        return pool
    row = conn.execute(
        "SELECT COALESCE(precio_medio, 0), COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        ("kg", int(producto_id)),
    ).fetchone()
    pmp, um = (float(row[0] or 0), str(row[1] or "kg")) if row else (0.0, "kg")
    registrar_movimiento_ingreso_bodega(
        conn,
        producto_id=int(producto_id),
        cantidad=delta,
        fecha=str(fecha)[:10],
        precio_medio=pmp,
        unidad_medida=um,
        centro_costo=CC_INGRESO_CANONICO,
    )
    sincronizar_inventario_desde_pool(conn, producto_id)
    return stock_pool(conn, producto_id)


def stock_pool(conn: sqlite3.Connection, producto_id: int) -> float:
    """Disponible bodega = ingresos (EL ESPINO / Cerezos / CEREZOS) − todas las salidas."""
    sql = f"SELECT {_case_pool_sql()} FROM movimientos WHERE producto_id = ?"
    row = conn.execute(sql, (*_CCS_INGRESO, producto_id)).fetchone()
    if row and row[0] is not None:
        return float(row[0])
    return 0.0


def stock_pool_map(conn: sqlite3.Connection) -> dict[int, float]:
    sql = f"SELECT producto_id, {_case_pool_sql()} AS pool FROM movimientos GROUP BY producto_id"
    rows = conn.execute(sql, _CCS_INGRESO).fetchall()
    return {int(r[0]): float(r[1] or 0) for r in rows}


def tiene_movimientos_bodega(conn: sqlite3.Connection, producto_id: int) -> bool:
    ph = ",".join("?" * len(_CCS_INGRESO))
    row = conn.execute(
        f"""SELECT 1 FROM movimientos WHERE producto_id = ?
           AND (tipo = 'Salida'
                OR (tipo = 'Ingreso' AND UPPER(TRIM(centro_costo)) IN ({ph})))
           LIMIT 1""",
        (producto_id, *_CCS_INGRESO),
    ).fetchone()
    return row is not None


def ids_productos_con_kardex_bodega(conn: sqlite3.Connection) -> set[int]:
    ph = ",".join("?" * len(_CCS_INGRESO))
    rows = conn.execute(
        f"""SELECT DISTINCT producto_id FROM movimientos
           WHERE tipo = 'Salida'
              OR (tipo = 'Ingreso' AND UPPER(TRIM(centro_costo)) IN ({ph}))""",
        _CCS_INGRESO,
    ).fetchall()
    return {int(r[0]) for r in rows}


def sincronizar_inventario_desde_pool(
    conn: sqlite3.Connection,
    producto_id: int | None = None,
) -> int:
    """Alinea inventario.stock al pool kardex (Espino)."""
    if producto_id is not None:
        pool = stock_pool(conn, producto_id)
        conn.execute("UPDATE inventario SET stock = ? WHERE id = ?", (pool, producto_id))
        return 1
    updated = 0
    for pid in ids_productos_con_kardex_bodega(conn):
        pool = stock_pool(conn, pid)
        conn.execute("UPDATE inventario SET stock = ? WHERE id = ?", (pool, pid))
        updated += 1
    return updated


def registrar_movimiento_ingreso_bodega(
    conn: sqlite3.Connection,
    *,
    producto_id: int,
    cantidad: float,
    fecha: str,
    precio_medio: float,
    unidad_medida: str,
    centro_costo: str | None = None,
) -> None:
    cc = (centro_costo or CC_INGRESO_CANONICO).strip() or CC_INGRESO_CANONICO
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (
            producto_id,
            "Ingreso",
            cantidad,
            str(fecha)[:10],
            cc,
            cantidad * float(precio_medio or 0),
            unidad_medida,
        ),
    )


def aplicar_compra_agro_en_bodega(
    conn: sqlite3.Connection,
    *,
    producto_id: int,
    cantidad: float,
    fecha: str,
    precio_medio: float,
    unidad_medida: str,
) -> None:
    """Tras compra agro: ingreso kardex bodega + inventario.stock = pool."""
    registrar_movimiento_ingreso_bodega(
        conn,
        producto_id=producto_id,
        cantidad=cantidad,
        fecha=fecha,
        precio_medio=precio_medio,
        unidad_medida=unidad_medida,
        centro_costo=CC_INGRESO_CANONICO,
    )
    sincronizar_inventario_desde_pool(conn, producto_id)


def productos_disponibles_libro_campo(
    conn: sqlite3.Connection,
    demo: Any,
    *,
    es_bodega_fn,
) -> list[dict[str, str]]:
    """Lista única para LC Espino (stock pool > 0 y pertenece a bodega)."""
    pool = stock_pool_map(conn)
    rows = conn.execute(
        "SELECT id, producto, COALESCE(unidad_medida, ?) AS um FROM inventario ORDER BY producto",
        (demo.DEFAULT_UNIDAD_INSUMO,),
    ).fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        pid = int(r[0])
        nombre = str(r[1])
        if not es_bodega_fn(nombre, conn, producto_id=pid):
            continue
        stock = stock_disponible_bodega(conn, pid)
        if stock <= 1e-9:
            continue
        out.append(
            {
                "producto": nombre,
                "stock_fmt": demo.f_cantidad(stock),
                "um": r[2],
            }
        )
    return out
