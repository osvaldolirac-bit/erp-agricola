"""Operaciones Comercial: Compras (CxP), Tesorería y Bodega.

Cotizaciones cubren ventas (servicio/producto). Tesorería solo paga proveedores.
Bodega solo mueve stock físico; ventas de servicio no tocan inventario.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from rmweb import core


def ensure_ops_schema(c) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS proveedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rut TEXT,
            razon_social TEXT NOT NULL,
            contacto TEXT,
            telefono TEXT,
            email TEXT,
            direccion TEXT,
            activo INTEGER DEFAULT 1,
            creado_en TEXT
        );
        CREATE TABLE IF NOT EXISTS facturas_compra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento TEXT NOT NULL,
            proveedor_id INTEGER NOT NULL,
            concepto TEXT,
            fecha_emision TEXT,
            fecha_vencimiento TEXT,
            neto REAL DEFAULT 0,
            iva REAL DEFAULT 0,
            total REAL DEFAULT 0,
            pagado REAL DEFAULT 0,
            saldo REAL DEFAULT 0,
            estado TEXT DEFAULT 'pendiente',
            afecta_stock INTEGER DEFAULT 0,
            notas TEXT,
            FOREIGN KEY(proveedor_id) REFERENCES proveedores(id)
        );
        CREATE TABLE IF NOT EXISTS factura_compra_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER NOT NULL,
            producto_id INTEGER,
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 1,
            costo_unitario REAL DEFAULT 0,
            total REAL DEFAULT 0,
            es_servicio INTEGER DEFAULT 0,
            FOREIGN KEY(factura_id) REFERENCES facturas_compra(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS pagos_compra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER NOT NULL,
            fecha TEXT,
            monto REAL,
            medio TEXT,
            nota TEXT,
            FOREIGN KEY(factura_id) REFERENCES facturas_compra(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER UNIQUE,
            codigo TEXT,
            nombre TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            stock REAL DEFAULT 0,
            costo_pmp REAL DEFAULT 0,
            activo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS inventario_movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventario_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            cantidad REAL NOT NULL,
            costo_unitario REAL DEFAULT 0,
            fecha TEXT,
            origen TEXT,
            origen_id INTEGER,
            nota TEXT,
            FOREIGN KEY(inventario_id) REFERENCES inventario(id)
        );
        CREATE TABLE IF NOT EXISTS remitos_venta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT UNIQUE,
            cotizacion_id INTEGER,
            cliente_id INTEGER NOT NULL,
            fecha TEXT,
            notas TEXT,
            cxc_id INTEGER,
            FOREIGN KEY(cotizacion_id) REFERENCES cotizaciones(id),
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        );
        CREATE TABLE IF NOT EXISTS remito_venta_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remito_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT 'un',
            cantidad REAL DEFAULT 1,
            es_servicio INTEGER DEFAULT 1,
            producto_id INTEGER,
            cotizacion_item_id INTEGER,
            FOREIGN KEY(remito_id) REFERENCES remitos_venta(id) ON DELETE CASCADE
        );
        """
    )
    core._ensure_columns(c, "proveedores", [("direccion", "TEXT"), ("creado_en", "TEXT")])
    core._ensure_columns(
        c,
        "productos",
        [("es_servicio", "INTEGER DEFAULT 0"), ("maneja_stock", "INTEGER DEFAULT 0")],
    )
    core._ensure_columns(
        c,
        "cotizaciones",
        [("tipo_venta", "TEXT DEFAULT 'servicio'")],
    )
    core._ensure_columns(
        c,
        "cotizacion_items",
        [("es_servicio", "INTEGER DEFAULT 1")],
    )

    try:
        from rmweb import ops_oc
        ops_oc.ensure_oc_schema(c)
    except Exception:
        pass

    try:
        from rmweb import ops_cc
        ops_cc.ensure_cc_schema(c)
    except Exception:
        pass


def recalc_factura_compra(c, factura_id: int) -> None:
    row = c.execute(
        "SELECT total, COALESCE((SELECT SUM(monto) FROM pagos_compra WHERE factura_id=?),0) AS pagado FROM facturas_compra WHERE id=?",
        (factura_id, factura_id),
    ).fetchone()
    if not row:
        return
    # Montos CxP en CLP enteros; evita saldos fantasma por centavos (p.ej. $0.58 → $1 en pantalla).
    total = float(row["total"] or 0)
    pagado = float(int(round(float(row["pagado"] or 0))))
    saldo = max(0.0, total - pagado)
    if saldo <= 0.009:
        estado = "pagado"
        saldo = 0.0
        pagado = total
    elif pagado > 0:
        estado = "parcial"
    else:
        estado = "pendiente"
    c.execute(
        "UPDATE facturas_compra SET total=?, pagado=?, saldo=?, estado=? WHERE id=?",
        (total, pagado, saldo, estado, factura_id),
    )


def _get_or_create_inventario(
    c,
    *,
    producto_id: int | None,
    codigo: str,
    nombre: str,
    unidad: str,
) -> int:
    if producto_id:
        row = c.execute(
            "SELECT id FROM inventario WHERE producto_id=?", (producto_id,)
        ).fetchone()
        if row:
            return int(row["id"])
    row = c.execute(
        "SELECT id FROM inventario WHERE lower(nombre)=lower(?) AND COALESCE(codigo,'')=?",
        (nombre, codigo or ""),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = c.execute(
        """
        INSERT INTO inventario (producto_id, codigo, nombre, unidad, stock, costo_pmp, activo)
        VALUES (?,?,?,?,0,0,1)
        """,
        (producto_id, codigo or None, nombre, unidad or "un"),
    )
    return int(cur.lastrowid)


def registrar_movimiento_stock(
    c,
    *,
    tipo: str,
    cantidad: float,
    costo_unitario: float = 0.0,
    producto_id: int | None = None,
    codigo: str = "",
    nombre: str = "",
    unidad: str = "un",
    origen: str = "manual",
    origen_id: int | None = None,
    nota: str = "",
    fecha: str | None = None,
) -> tuple[bool, str]:
    tipo = (tipo or "").strip().lower()
    if tipo not in {"entrada", "salida", "ajuste"}:
        return False, "Tipo de movimiento inválido."
    cant = float(cantidad or 0)
    if cant <= 0:
        return False, "Cantidad debe ser mayor a 0."
    if not (nombre or "").strip() and not producto_id:
        return False, "Indique producto o nombre."

    if producto_id and not nombre:
        p = c.execute(
            "SELECT codigo, nombre, unidad FROM productos WHERE id=?", (producto_id,)
        ).fetchone()
        if not p:
            return False, "Producto no encontrado."
        codigo = codigo or (p["codigo"] or "")
        nombre = p["nombre"]
        unidad = unidad or (p["unidad"] or "un")

    inv_id = _get_or_create_inventario(
        c, producto_id=producto_id, codigo=codigo, nombre=nombre, unidad=unidad
    )
    inv = c.execute("SELECT * FROM inventario WHERE id=?", (inv_id,)).fetchone()
    stock = float(inv["stock"] or 0)
    pmp = float(inv["costo_pmp"] or 0)
    costo = float(costo_unitario or 0)

    if tipo == "entrada":
        nuevo_stock = stock + cant
        if nuevo_stock > 0:
            pmp = ((stock * pmp) + (cant * costo)) / nuevo_stock if (stock + cant) else costo
        else:
            pmp = costo
        stock = nuevo_stock
    elif tipo == "salida":
        if cant > stock + 1e-9:
            return False, f"Stock insuficiente de {nombre} (disponible {stock:g})."
        stock = stock - cant
    else:  # ajuste: cantidad = nuevo stock absoluto via nota? usamos delta positivo/negativo encoded: costo unused, cantidad is NEW stock
        # For simplicity ajuste sets absolute stock to `cantidad`
        stock = cant
        cant = abs(cant - float(inv["stock"] or 0)) or cant

    c.execute(
        "UPDATE inventario SET stock=?, costo_pmp=?, codigo=COALESCE(?, codigo), unidad=COALESCE(?, unidad) WHERE id=?",
        (stock, pmp, codigo or None, unidad or None, inv_id),
    )
    c.execute(
        """
        INSERT INTO inventario_movimientos
        (inventario_id, tipo, cantidad, costo_unitario, fecha, origen, origen_id, nota)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            inv_id,
            tipo,
            float(cantidad or 0),
            costo,
            fecha or core.hoy_chile().isoformat(),
            origen,
            origen_id,
            nota or "",
        ),
    )
    return True, "Movimiento registrado."


def aplicar_entrada_compra(c, factura_id: int) -> tuple[bool, str]:
    fac = c.execute("SELECT * FROM facturas_compra WHERE id=?", (factura_id,)).fetchone()
    if not fac:
        return False, "Factura no encontrada."
    if not int(fac["afecta_stock"] or 0):
        return True, "Sin impacto en bodega."
    items = c.execute(
        "SELECT * FROM factura_compra_items WHERE factura_id=? AND COALESCE(es_servicio,0)=0",
        (factura_id,),
    ).fetchall()
    if not items:
        return True, "Sin ítems de material."
    for it in items:
        ok, msg = registrar_movimiento_stock(
            c,
            tipo="entrada",
            cantidad=float(it["cantidad"] or 0),
            costo_unitario=float(it["costo_unitario"] or 0),
            producto_id=it["producto_id"],
            nombre=it["descripcion"],
            unidad=it["unidad"] or "un",
            origen="compra",
            origen_id=factura_id,
            nota=f"Compra {fac['documento']}",
            fecha=fac["fecha_emision"] or core.hoy_chile().isoformat(),
        )
        if not ok:
            return False, msg
    return True, "Entrada a bodega aplicada."



def aplicar_salida_cotizacion_producto(c, cot_id: int) -> tuple[bool, str]:
    """Descuenta stock al aprobar una cotización de venta producto."""
    cot = c.execute("SELECT * FROM cotizaciones WHERE id=?", (cot_id,)).fetchone()
    if not cot:
        return False, "Cotización no encontrada."
    tipo = (cot["tipo_venta"] if "tipo_venta" in cot.keys() else None) or "servicio"
    if str(tipo).strip().lower() != "producto":
        return True, "Sin impacto en bodega (venta servicio)."
    ya = c.execute(
        """
        SELECT id FROM inventario_movimientos
        WHERE origen=? AND origen_id=? LIMIT 1
        """,
        ("cotizacion", cot_id),
    ).fetchone()
    if ya:
        return True, "Salida de bodega ya aplicada."
    items = c.execute(
        """
        SELECT * FROM cotizacion_items
        WHERE cotizacion_id=?
        ORDER BY COALESCE(orden,0), id
        """,
        (cot_id,),
    ).fetchall()
    if not items:
        return True, "Sin ítems."
    n = 0
    for it in items:
        es_srv = 1
        if "es_servicio" in it.keys() and it["es_servicio"] is not None:
            es_srv = int(it["es_servicio"] or 0)
        elif it["producto_id"]:
            prow = c.execute(
                "SELECT COALESCE(es_servicio,0) AS es_servicio FROM productos WHERE id=?",
                (it["producto_id"],),
            ).fetchone()
            es_srv = int(prow["es_servicio"] or 0) if prow else 0
        else:
            es_srv = 0
        if es_srv:
            continue
        cant = float(it["cantidad"] or 0)
        if cant <= 0:
            continue
        ok, msg = registrar_movimiento_stock(
            c,
            tipo="salida",
            cantidad=cant,
            costo_unitario=0.0,
            producto_id=it["producto_id"],
            nombre=it["descripcion"],
            unidad=it["unidad"] or "un",
            origen="cotizacion",
            origen_id=cot_id,
            nota=f"Venta producto {cot['folio']}",
            fecha=cot["fecha"] or core.hoy_chile().isoformat(),
        )
        if not ok:
            return False, msg
        n += 1
    if n == 0:
        return True, "Sin materiales con stock para descontar."
    return True, f"Salida de bodega aplicada ({n} ítem(s))."

def next_remito_folio(c) -> str:
    year = core.hoy_chile().year
    pref = f"REM-{year}-"
    row = c.execute(
        "SELECT folio FROM remitos_venta WHERE folio LIKE ? ORDER BY id DESC LIMIT 1",
        (pref + "%",),
    ).fetchone()
    n = 1
    if row and row["folio"]:
        try:
            n = int(str(row["folio"]).split("-")[-1]) + 1
        except ValueError:
            n = 1
    return f"{pref}{n:04d}"


def cxp_estado_class(estado: str) -> str:
    e = (estado or "").lower()
    if e == "pagado":
        return "pagado"
    if e == "parcial":
        return "ingresada"
    return "pendiente"


def cxp_estado_label(estado: str) -> str:
    e = (estado or "").lower()
    return {"pendiente": "Pendiente", "parcial": "Parcial", "pagado": "Pagado"}.get(e, estado or "—")


def kpis_cxp(c) -> dict[str, Any]:
    rows = c.execute(
        "SELECT estado, total, pagado, saldo FROM facturas_compra"
    ).fetchall()
    total_docs = len(rows)
    pend = [r for r in rows if (r["estado"] or "") == "pendiente"]
    parc = [r for r in rows if (r["estado"] or "") == "parcial"]
    pag = [r for r in rows if (r["estado"] or "") == "pagado"]
    sum_total = sum(float(r["total"] or 0) for r in rows)
    sum_pagado = sum(float(r["pagado"] or 0) for r in rows)
    sum_saldo = sum(float(r["saldo"] or 0) for r in rows)
    return {
        "total_docs": total_docs,
        "pend_n": len(pend),
        "pend_m": sum(float(r["saldo"] or 0) for r in pend),
        "parc_n": len(parc),
        "parc_m": sum(float(r["saldo"] or 0) for r in parc),
        "pag_n": len(pag),
        "pag_m": sum(float(r["total"] or 0) for r in pag),
        "sum_total": sum_total,
        "sum_pagado": sum_pagado,
        "sum_saldo": sum_saldo,
        "tasa": (100.0 * len(pag) / total_docs) if total_docs else 0.0,
    }
