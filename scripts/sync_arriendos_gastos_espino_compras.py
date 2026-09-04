#!/usr/bin/env python3
"""Copia arriendos de gastos_espino a facturas (Compras) si aún no existen."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

RAZON_DEFAULT = "La Concepción"
TIPO_GASTO = "Arriendos"


def _es_arriendo(item: str, documento: str) -> bool:
    txt = f"{item or ''} {documento or ''}".upper()
    return "ARRIENDO" in txt or "PAOLA" in txt


def _ya_existe(conn, fecha, documento, item, monto) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM facturas
        WHERE nro_documento NOT LIKE '%_P'
          AND ABS(COALESCE(monto_total, 0) - ?) < 1
          AND (
            TRIM(COALESCE(concepto, '')) = ?
            OR (TRIM(COALESCE(nro_documento, '')) = ? AND fecha_compra = ?)
          )
        LIMIT 1
        """,
        (float(monto), str(item or "").strip(), str(documento or "").strip(), str(fecha)[:10]),
    ).fetchone()
    return row is not None


def _siguiente_int(conn, fecha) -> str:
    pref = f"INT-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        "SELECT COUNT(*) FROM facturas WHERE nro_documento LIKE ? AND nro_documento NOT LIKE '%_P'",
        (pref + "%",),
    ).fetchone()[0]
    return f"{pref}{int(n) + 1:02d}"


def _proveedor_desde_item(item: str) -> str:
    item = (item or "").strip()
    if "MARIA PAOLA" in item.upper() or "MARÍA PAOLA" in item.upper():
        return "María Paola Torres Ortiz"
    if "ARRIENDO" in item.upper():
        part = item.split("Arriendo", 1)[-1].strip(" :-")
        return part[:120] if part else "Arriendo"
    return item[:120] or "Arriendo"


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, fecha, documento, item, monto FROM gastos_espino WHERE ABS(COALESCE(monto, 0)) > 0.01"
    ).fetchall()
    insertados = 0
    for _gid, fecha, documento, item, monto in rows:
        if not _es_arriendo(str(item), str(documento)):
            continue
        if _ya_existe(conn, fecha, documento, item, monto):
            print(f"SKIP ya existe: {item[:60]} ${monto:,.0f}")
            continue
        doc = str(documento or "").strip()
        if doc.upper().startswith("INT-") and not doc.endswith("_P"):
            nro = doc
        elif doc.upper().startswith("INT/"):
            nro = doc.replace("/", "-")
        else:
            nro = _siguiente_int(conn, fecha)
        prov = _proveedor_desde_item(str(item))
        fv = str(fecha)[:10]
        cur.execute(
            """
            INSERT INTO facturas
            (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, tipo,
             concepto, razon_social, tipo_gasto, estado, monto_pagado, fecha_pago, metodo_pago)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                nro,
                prov,
                fv,
                fv,
                float(monto),
                "Gasto Operacional",
                str(item or "").strip()[:500],
                RAZON_DEFAULT,
                TIPO_GASTO,
                "Pagado",
                float(monto),
                fv,
                "Histórico (gastos_espino)",
            ),
        )
        insertados += 1
        print(f"INSERT {nro} | {prov} | ${float(monto):,.0f} | {str(item)[:50]}")
    conn.commit()
    conn.close()
    print(f"OK — {insertados} arriendo(s) agregados al historial Compras.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
