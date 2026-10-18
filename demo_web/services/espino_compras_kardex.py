"""Utilidades kardex bodega desde compras agro (facturas.concepto)."""
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


def _fecha_cmp(fecha: str) -> str:
    return str(fecha or "").strip()[:10]


def origen_compra_ingreso(
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    cant: float,
    fecha: str,
) -> str | None:
    """Busca factura agro que explique un ingreso kardex (nro doc + fecha compra)."""
    nombre_u = (producto_nombre or "").upper().strip()
    f_mov = _fecha_cmp(fecha)
    candidatos: list[tuple[str, str, str]] = []
    for nro, fcompra, concepto in conn.execute(
        """SELECT nro_documento, fecha_compra, concepto FROM facturas
           WHERE nro_documento NOT LIKE '%_P' AND concepto IS NOT NULL
             AND date(fecha_compra)=date(?)
           ORDER BY fecha_compra, id""",
        (f_mov,),
    ):
        for item in parse_concepto_compra(str(concepto or "")):
            if abs(float(item["cantidad"]) - float(cant)) > 1e-4:
                continue
            pid = match_producto_id(conn, item["producto"])
            item_u = item["producto"].upper().strip()
            if pid == producto_id or item_u == nombre_u or nombre_u in item_u or item_u in nombre_u:
                candidatos.append((str(nro), _fecha_cmp(fcompra), str(concepto or "")))
                break
    if not candidatos:
        return None
    nro, fcompra, _ = max(candidatos, key=lambda t: (t[1], t[0]))
    return f"Compra N° {nro} ({fcompra})"
