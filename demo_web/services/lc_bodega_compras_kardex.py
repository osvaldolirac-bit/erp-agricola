"""Compras agro LC → ingreso en kardex bodega (movimientos + stock)."""
from __future__ import annotations

import sqlite3

from demo_web.services.bodega_kardex import ETIQUETA_BODEGA
from demo_web.services.espino_compras_kardex import match_producto_id, parse_concepto_compra

CC_INGRESO_LC = ETIQUETA_BODEGA  # "BODEGA"


def _tiene_ingreso(
    conn: sqlite3.Connection,
    producto_id: int,
    fecha: str,
    cantidad: float,
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM movimientos
           WHERE producto_id=? AND tipo='Ingreso' AND date(fecha)=date(?)
             AND ABS(cantidad - ?) < 0.02
           LIMIT 1""",
        (producto_id, str(fecha)[:10], float(cantidad)),
    ).fetchone()
    return row is not None


def registrar_ingreso_compra_lc(
    conn: sqlite3.Connection,
    *,
    producto_id: int,
    cantidad: float,
    fecha: str,
    precio_medio: float,
    unidad_medida: str,
) -> None:
    cant = float(cantidad)
    if cant <= 0:
        return
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (
            producto_id,
            "Ingreso",
            cant,
            str(fecha)[:10],
            CC_INGRESO_LC,
            cant * float(precio_medio or 0),
            unidad_medida or "kg",
        ),
    )


def aplicar_compra_agro_en_bodega_lc(
    conn: sqlite3.Connection,
    *,
    producto_id: int,
    cantidad: float,
    fecha: str,
    precio_medio: float,
    unidad_medida: str,
    actualizar_stock: bool = True,
) -> None:
    """Registra ingreso kardex; opcionalmente suma inventario.stock (compras nuevas)."""
    if _tiene_ingreso(conn, producto_id, fecha, cantidad):
        return
    registrar_ingreso_compra_lc(
        conn,
        producto_id=producto_id,
        cantidad=cantidad,
        fecha=fecha,
        precio_medio=precio_medio,
        unidad_medida=unidad_medida,
    )
    if actualizar_stock:
        conn.execute(
            "UPDATE inventario SET stock = COALESCE(stock, 0) + ? WHERE id = ?",
            (float(cantidad), producto_id),
        )


def reparar_ingresos_desde_factura(
    conn: sqlite3.Connection,
    *,
    nro_documento: str,
    fecha_compra: str,
    concepto: str,
    monto_total: float,
    dry_run: bool = False,
) -> list[str]:
    """Crea movimientos Ingreso faltantes para una factura agro ya guardada (sin tocar stock)."""
    msgs: list[str] = []
    items = parse_concepto_compra(concepto or "")
    if not items:
        return msgs
    neto_total = float(monto_total or 0) / 1.19 if monto_total else 0.0
    for item in items:
        pid = match_producto_id(conn, item["producto"])
        if not pid:
            msgs.append(f"SKIP {nro_documento}: sin match inventario «{item['producto']}»")
            continue
        cant = float(item["cantidad"])
        if _tiene_ingreso(conn, pid, fecha_compra, cant):
            continue
        row = conn.execute(
            "SELECT COALESCE(precio_medio,0), COALESCE(unidad_medida,'kg') FROM inventario WHERE id=?",
            (pid,),
        ).fetchone()
        pmp = float(row[0] or 0) if row else 0.0
        um = str(row[1] or item.get("um") or "kg") if row else item.get("um") or "kg"
        if pmp <= 0 and neto_total > 0:
            pmp = neto_total / cant if cant > 0 else 0.0
        msgs.append(
            f"{'[dry] ' if dry_run else ''}Ingreso kardex {item['producto']} "
            f"+{cant} {um} ({fecha_compra}) doc {nro_documento}"
        )
        if not dry_run:
            registrar_ingreso_compra_lc(
                conn,
                producto_id=pid,
                cantidad=cant,
                fecha=str(fecha_compra)[:10],
                precio_medio=pmp,
                unidad_medida=um,
            )
    return msgs


def reparar_compras_agro_recientes(
    conn: sqlite3.Connection,
    *,
    dias: int = 120,
    dry_run: bool = False,
) -> list[str]:
    out: list[str] = []
    rows = conn.execute(
        """SELECT nro_documento, fecha_compra, concepto, monto_total
           FROM facturas
           WHERE nro_documento NOT LIKE '%_P'
             AND concepto LIKE '% x %'
             AND fecha_compra >= date('now', ?)
           ORDER BY fecha_compra, id""",
        (f"-{int(dias)} days",),
    ).fetchall()
    for nro, fcompra, concepto, monto in rows:
        out.extend(
            reparar_ingresos_desde_factura(
                conn,
                nro_documento=str(nro),
                fecha_compra=str(fcompra),
                concepto=str(concepto or ""),
                monto_total=float(monto or 0),
                dry_run=dry_run,
            )
        )
    return out
