"""Utilidades kardex bodega El Espino desde compras agro (facturas.concepto)."""
from __future__ import annotations

import re
import sqlite3

_CONCEPTO_ITEM_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:(\w+)\s+)?x\s+([^,\]]+)",
    re.IGNORECASE,
)


def parse_concepto_compra(concepto: str) -> list[dict]:
    """Parsea detalle agro en facturas.concepto → cantidad, um y nombre producto."""
    text = (concepto or "").strip()
    if not text or not _CONCEPTO_ITEM_RE.search(text):
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    items: list[dict] = []
    for m in _CONCEPTO_ITEM_RE.finditer(text):
        qty = float(m.group(1).replace(",", "."))
        um = (m.group(2) or "").strip().lower()
        prod = m.group(3).strip().rstrip(",").strip()
        if qty <= 0 or not prod:
            continue
        items.append({"cantidad": qty, "um": um, "producto": prod})
    return items


def match_producto_id(conn: sqlite3.Connection, nombre: str) -> int | None:
    """Resuelve inventario.id desde nombre en detalle de compra."""
    n = (nombre or "").upper().strip()
    if not n:
        return None
    row = conn.execute(
        "SELECT id FROM inventario WHERE UPPER(TRIM(producto))=?",
        (n,),
    ).fetchone()
    if row:
        return int(row[0])
    rows = conn.execute(
        "SELECT id, producto FROM inventario WHERE UPPER(TRIM(producto)) LIKE ?",
        (f"%{n}%",),
    ).fetchall()
    if len(rows) == 1:
        return int(rows[0][0])
    if len(rows) > 1:
        exact = [r for r in rows if str(r[1]).upper().strip() == n]
        if len(exact) == 1:
            return int(exact[0][0])
    return None


def origen_compra_ingreso(
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    cant: float,
    fecha: str,
) -> str | None:
    """Busca factura agro que explique un ingreso kardex (nro doc + fecha compra)."""
    nombre_u = (producto_nombre or "").upper().strip()
    for nro, fcompra, concepto in conn.execute(
        """SELECT nro_documento, fecha_compra, concepto FROM facturas
           WHERE nro_documento NOT LIKE '%_P' AND concepto IS NOT NULL
           ORDER BY fecha_compra, id"""
    ):
        if str(fcompra) != str(fecha):
            continue
        for item in parse_concepto_compra(str(concepto or "")):
            if abs(float(item["cantidad"]) - cant) > 1e-4:
                continue
            pid = match_producto_id(conn, item["producto"])
            if pid == producto_id:
                return f"Compra N° {nro} ({fcompra})"
            if item["producto"].upper().strip() == nombre_u:
                return f"Compra N° {nro} ({fcompra})"
    return None


def formatear_concepto_insumos(items: list[dict]) -> str:
    """Reconstruye el detalle [cant um x producto] con las cantidades nuevas."""
    partes: list[str] = []
    for it in items:
        qty = _fmt_qty_concepto(float(it["cantidad"]))
        um = (it.get("um") or "").strip()
        prod = (it.get("producto") or "").strip()
        if um:
            partes.append(f"{qty} {um} x {prod}")
        else:
            partes.append(f"{qty}x {prod}")
    return "[" + ", ".join(partes) + "]"


def _fmt_qty_concepto(q: float) -> str:
    s = f"{float(q):.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s or "0.0"


def _ingresos_producto(conn: sqlite3.Connection, producto_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, cantidad, fecha, COALESCE(valor_imputado, 0)
           FROM movimientos
           WHERE producto_id=? AND lower(tipo) LIKE 'ing%'
           ORDER BY fecha, id""",
        (int(producto_id),),
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "cantidad": float(r[1] or 0),
            "fecha": str(r[2] or "")[:10],
            "valor": float(r[3] or 0),
        }
        for r in rows
    ]


def _elegir_ingreso_compra(
    movs: list[dict],
    qty: float,
    fecha: str,
    usados: set[int],
) -> dict | None:
    """Elige el ingreso de esta compra. None si hay más de un candidato."""
    libres = [m for m in movs if m["id"] not in usados]
    fecha = str(fecha or "")[:10]

    def misma_fecha(m: dict) -> bool:
        return m["fecha"] == fecha

    def misma_cant(m: dict) -> bool:
        return abs(m["cantidad"] - qty) <= 1e-4

    exactos = [m for m in libres if misma_fecha(m) and misma_cant(m)]
    if len(exactos) == 1:
        return exactos[0]
    if len(exactos) > 1:
        return None
    por_cant = [m for m in libres if misma_cant(m)]
    if len(por_cant) == 1:
        return por_cant[0]
    if len(por_cant) > 1:
        del_dia = [m for m in por_cant if misma_fecha(m)]
        return del_dia[0] if len(del_dia) == 1 else None
    del_dia = [m for m in libres if misma_fecha(m)]
    if len(del_dia) == 1:
        return del_dia[0]
    return None


def _stock_neto_movimientos(conn: sqlite3.Connection, producto_id: int) -> float:
    row = conn.execute(
        """SELECT SUM(CASE
               WHEN lower(tipo) LIKE 'ing%' THEN cantidad
               WHEN lower(tipo) LIKE 'sal%' THEN -cantidad
               ELSE 0 END)
           FROM movimientos WHERE producto_id=?""",
        (int(producto_id),),
    ).fetchone()
    return float(row[0] or 0) if row else 0.0


def _precio_medio_ingresos(conn: sqlite3.Connection, producto_id: int) -> float | None:
    from demo_web.services.espino_scope import centros_costo_bodega_espino

    ccs = tuple(sorted(centros_costo_bodega_espino()))
    if not ccs:
        return None
    ph = ",".join("?" * len(ccs))
    row = conn.execute(
        f"""SELECT SUM(cantidad), SUM(COALESCE(valor_imputado, 0))
            FROM movimientos
            WHERE producto_id=? AND lower(tipo) LIKE 'ing%'
              AND UPPER(centro_costo) IN ({ph})""",
        (int(producto_id), *ccs),
    ).fetchone()
    qty = float(row[0] or 0) if row else 0.0
    if qty <= 0:
        return None
    return float(row[1] or 0) / qty


def aplicar_cantidades_insumo_en_bodega(
    conn: sqlite3.Connection,
    *,
    concepto: str,
    fecha_old: str,
    fecha_new: str,
    cantidades: list[float],
    stock_desde_kardex: bool,
) -> tuple[str, list[str]]:
    """Actualiza el detalle y el ingreso de bodega de cada línea.

    En La Concepción el stock se mueve por la diferencia. En El Espino el stock
    se vuelve a calcular desde el kardex. Si no hay un ingreso único, el detalle
    cambia y el stock de esa línea queda igual.
    """
    lineas = parse_concepto_compra(concepto)
    if len(cantidades) != len(lineas):
        raise ValueError("La cantidad de líneas no coincide con el documento.")
    nuevas: list[dict] = []
    for it, cant in zip(lineas, cantidades):
        qty = float(cant)
        if qty <= 0:
            raise ValueError(f"La cantidad de {it['producto']} debe ser mayor a cero.")
        nuevas.append({**it, "cantidad_doc": float(it["cantidad"]), "cantidad": qty})

    avisos: list[str] = []
    usados: set[int] = set()
    fecha_old_s = str(fecha_old or "")[:10]
    fecha_new_s = str(fecha_new or fecha_old_s)[:10]
    for it in nuevas:
        qty_doc = float(it["cantidad_doc"])
        qty_new = float(it["cantidad"])
        cambio = abs(qty_new - qty_doc) > 1e-6 or fecha_new_s != fecha_old_s
        pid = match_producto_id(conn, it["producto"])
        if pid is None:
            if cambio:
                avisos.append(f"{it['producto']}: no está en bodega; el stock no cambió.")
            continue
        mov = _elegir_ingreso_compra(
            _ingresos_producto(conn, pid), qty_doc, fecha_old_s, usados,
        )
        if mov is None:
            if cambio:
                it["cantidad"] = qty_doc
                avisos.append(
                    f"{it['producto']}: no hay un ingreso único de esta compra; la cantidad y el stock no cambiaron."
                )
            continue
        usados.add(mov["id"])
        qty_mov = float(mov["cantidad"])
        delta = qty_new - qty_mov
        if abs(delta) <= 1e-9 and mov["fecha"] == fecha_new_s:
            continue
        valor = float(mov["valor"])
        if abs(delta) > 1e-9 and qty_mov > 0:
            valor = round(valor * (qty_new / qty_mov), 2)
        conn.execute(
            "UPDATE movimientos SET cantidad=?, fecha=?, valor_imputado=? WHERE id=?",
            (qty_new, fecha_new_s, valor, mov["id"]),
        )
        if stock_desde_kardex:
            stock = _stock_neto_movimientos(conn, pid)
            conn.execute("UPDATE inventario SET stock=? WHERE id=?", (stock, pid))
            pmp = _precio_medio_ingresos(conn, pid)
            if pmp is not None:
                conn.execute(
                    "UPDATE inventario SET precio_medio=? WHERE id=?",
                    (round(pmp, 4), pid),
                )
        elif abs(delta) > 1e-9:
            conn.execute(
                "UPDATE inventario SET stock = COALESCE(stock, 0) + ? WHERE id=?",
                (delta, pid),
            )
        if abs(delta) > 1e-9:
            row_st = conn.execute("SELECT stock FROM inventario WHERE id=?", (pid,)).fetchone()
            stock = float(row_st[0] or 0) if row_st else 0.0
            um = (it.get("um") or "").strip()
            avisos.append(
                f"{it['producto']}: {_fmt_qty_concepto(qty_mov)} → {_fmt_qty_concepto(qty_new)}"
                f"{(' ' + um) if um else ''}. Stock bodega {_fmt_qty_concepto(stock)}."
            )
    return formatear_concepto_insumos(nuevas), avisos
