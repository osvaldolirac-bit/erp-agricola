"""Helpers Órdenes de Compra (paso previo a facturas_compra)."""
from __future__ import annotations

from datetime import date
from typing import Any

from rmweb import core


OC_SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS ordenes_compra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT UNIQUE NOT NULL,
            proveedor_id INTEGER NOT NULL,
            concepto TEXT,
            fecha TEXT,
            fecha_entrega TEXT,
            neto REAL DEFAULT 0,
            iva REAL DEFAULT 0,
            total REAL DEFAULT 0,
            estado TEXT DEFAULT 'borrador',
            notas TEXT,
            factura_id INTEGER,
            creado_en TEXT,
            FOREIGN KEY(proveedor_id) REFERENCES proveedores(id),
            FOREIGN KEY(factura_id) REFERENCES facturas_compra(id)
        );
        CREATE TABLE IF NOT EXISTS orden_compra_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orden_id INTEGER NOT NULL,
            producto_id INTEGER,
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 1,
            costo_unitario REAL DEFAULT 0,
            total REAL DEFAULT 0,
            es_servicio INTEGER DEFAULT 0,
            FOREIGN KEY(orden_id) REFERENCES ordenes_compra(id) ON DELETE CASCADE
        );
"""


def ensure_oc_schema(c) -> None:
    c.executescript(OC_SCHEMA_SQL)
    core._ensure_columns(
        c,
        "facturas_compra",
        [("orden_compra_id", "INTEGER")],
    )


def oc_estado_class(estado: str) -> str:
    e = (estado or "").lower()
    return {
        "borrador": "ingresada",
        "emitida": "abonado",
        "convertida": "aprobada",
        "anulada": "rechazada",
    }.get(e, "pendiente")


def oc_estado_label(estado: str) -> str:
    e = (estado or "").lower()
    return {
        "borrador": "Borrador",
        "emitida": "Emitida",
        "convertida": "Convertida",
        "anulada": "Anulada",
    }.get(e, estado or "—")


def kpis_oc(c) -> dict[str, Any]:
    rows = c.execute("SELECT estado, total FROM ordenes_compra").fetchall()
    total = len(rows)
    sum_total = sum(float(r["total"] or 0) for r in rows)
    abiertas = sum(1 for r in rows if (r["estado"] or "") in ("borrador", "emitida"))
    convertidas = sum(1 for r in rows if (r["estado"] or "") == "convertida")
    anuladas = sum(1 for r in rows if (r["estado"] or "") == "anulada")
    return {
        "total": total,
        "sum_total": sum_total,
        "abiertas": abiertas,
        "convertidas": convertidas,
        "anuladas": anuladas,
    }


def next_oc_folio(c) -> str:
    return core.next_code(c, "ordenes_compra", "folio", "OC")


def iva_pct(c) -> float:
    try:
        return float(core.param(c, "iva", 19.0) or 19.0)
    except Exception:
        return 19.0


def parse_oc_lineas(form, productos) -> tuple[list[tuple], float]:
    descs = form.getlist("item_desc")
    uns = form.getlist("item_unidad")
    cants = form.getlist("item_cant")
    costos = form.getlist("item_costo")
    pids = form.getlist("item_producto_id")
    lineas: list[tuple] = []
    neto = 0.0
    for i, desc in enumerate(descs):
        desc = (desc or "").strip()
        if not desc:
            continue
        try:
            cant = float(cants[i] or 1)
        except (IndexError, ValueError):
            cant = 1.0
        try:
            costo = float(costos[i] or 0)
        except (IndexError, ValueError):
            costo = 0.0
        try:
            pid = int(pids[i] or 0) or None
        except (IndexError, ValueError):
            pid = None
        try:
            un = (uns[i] or "un").strip() or "un"
        except IndexError:
            un = "un"
        es_serv = 1 if form.get(f"item_servicio_{i}") else 0
        if not es_serv and pid:
            prow = next((p for p in productos if int(p["id"]) == pid), None)
            if prow and int(prow["es_servicio"] or 0):
                es_serv = 1
        total_l = round(cant * costo, 2)
        neto += total_l
        lineas.append((pid, desc, un, cant, costo, total_l, es_serv))
    return lineas, neto


def save_oc_items(c, orden_id: int, lineas: list[tuple]) -> None:
    c.execute("DELETE FROM orden_compra_items WHERE orden_id=?", (orden_id,))
    for pid, desc, un, cant, costo, total_l, es_serv in lineas:
        c.execute(
            """
            INSERT INTO orden_compra_items
            (orden_id, producto_id, descripcion, unidad, cantidad, costo_unitario, total, es_servicio)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (orden_id, pid, desc, un, cant, costo, total_l, es_serv),
        )


def convertir_oc_a_compra(c, orden_id: int, documento: str | None = None) -> tuple[bool, str | int]:
    """Crea facturas_compra + ítems desde la OC. No aplica stock (el usuario lo define en Compra)."""
    ensure_oc_schema(c)
    oc = c.execute("SELECT * FROM ordenes_compra WHERE id=?", (orden_id,)).fetchone()
    if not oc:
        return False, "Orden no encontrada"
    estado = (oc["estado"] or "").lower()
    if estado == "convertida":
        return False, "La OC ya fue convertida en compra"
    if estado == "anulada":
        return False, "No se puede convertir una OC anulada"
    items = c.execute(
        "SELECT * FROM orden_compra_items WHERE orden_id=? ORDER BY id",
        (orden_id,),
    ).fetchall()
    if not items:
        return False, "La OC no tiene ítems"

    folio = oc["folio"]
    doc = (documento or "").strip() or f"FC-{folio}"
    fe = (oc["fecha"] or date.today().isoformat())
    # vencimiento por defecto +30 días
    try:
        from datetime import timedelta

        fv = (date.fromisoformat(fe) + timedelta(days=30)).isoformat()
    except Exception:
        fv = fe

    neto = float(oc["neto"] or 0)
    iva = float(oc["iva"] or 0)
    total = float(oc["total"] or 0)
    cur = c.execute(
        """
        INSERT INTO facturas_compra
        (documento, proveedor_id, concepto, fecha_emision, fecha_vencimiento,
         neto, iva, total, pagado, saldo, estado, afecta_stock, notas, orden_compra_id)
        VALUES (?,?,?,?,?,?,?,?,0,?,'pendiente',0,?,?)
        """,
        (
            doc,
            int(oc["proveedor_id"]),
            oc["concepto"] or f"Según {folio}",
            fe,
            fv,
            neto,
            iva,
            total,
            total,
            (oc["notas"] or "") + (f" · Origen {folio}" if oc["notas"] else f"Origen {folio}"),
            orden_id,
        ),
    )
    fid = int(cur.lastrowid)
    for it in items:
        c.execute(
            """
            INSERT INTO factura_compra_items
            (factura_id, producto_id, descripcion, unidad, cantidad, costo_unitario, total, es_servicio)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                fid,
                it["producto_id"],
                it["descripcion"],
                it["unidad"],
                it["cantidad"],
                it["costo_unitario"],
                it["total"],
                it["es_servicio"],
            ),
        )
    c.execute(
        "UPDATE ordenes_compra SET estado='convertida', factura_id=? WHERE id=?",
        (fid, orden_id),
    )
    return True, fid
