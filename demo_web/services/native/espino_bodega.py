"""Bodega sector El Espino — stock por CC del huerto, sin alterar inventario global ni La Concepción."""
from __future__ import annotations

import pandas as pd
from flask import request, url_for

from demo_web.services.espino_scope import (
    BODEGA_CC_ESPINO,
    CC_MOVIMIENTOS_BODEGA_ESPINO,
    centros_costo_bodega_espino,
)
from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import hoy_demo

# CC en nuevos movimientos; etiqueta UI = BODEGA_CC_ESPINO.
CC_ESPINO = CC_MOVIMIENTOS_BODEGA_ESPINO
ETIQUETA_BODEGA = BODEGA_CC_ESPINO

PDF_STOCK_FILENAME = "STOCK_BODEGA_EL_ESPINO.pdf"

BODEGA_SECCIONES = [
    ("bodega", "📦 BODEGA"),
]

BODEGA_OPS = [
    ("stock", "📊 Stock actual"),
    ("nuevo", "➕ Crear producto"),
]


def bodega_secciones() -> list[tuple[str, str]]:
    return list(BODEGA_SECCIONES)


def _es_producto_bodega_espino(nombre: str) -> bool:
    """Todo el inventario del tenant Espino pertenece a su bodega."""
    _ = nombre
    return True


def _stock_cc_map(conn) -> dict[int, float]:
    """Stock kardex bodega El Espino (todos los CC históricos del huerto)."""
    ccs = sorted(centros_costo_bodega_espino())
    placeholders = ",".join("?" * len(ccs))
    rows = conn.execute(
        f"""SELECT producto_id,
                   SUM(CASE WHEN tipo = 'Ingreso' THEN cantidad ELSE -cantidad END) AS stock_cc
            FROM movimientos
            WHERE UPPER(centro_costo) IN ({placeholders})
            GROUP BY producto_id""",
        ccs,
    ).fetchall()
    return {int(r[0]): float(r[1] or 0) for r in rows}


def _stock_disponible(stock_mov: float, inventario_stock: float) -> float:
    """Kardex CC; si no hay ingresos registrados, usa inventario.stock."""
    if stock_mov > 1e-9:
        return stock_mov
    return max(float(inventario_stock or 0), 0.0)


def _stock_cc(conn, producto_id: int, *, inventario_stock: float = 0.0) -> float:
    ccs = sorted(centros_costo_bodega_espino())
    placeholders = ",".join("?" * len(ccs))
    row = conn.execute(
        f"""SELECT SUM(CASE WHEN tipo = 'Ingreso' THEN cantidad ELSE -cantidad END)
            FROM movimientos
            WHERE UPPER(centro_costo) IN ({placeholders}) AND producto_id = ?""",
        (*ccs, producto_id),
    ).fetchone()
    stock_mov = float(row[0] or 0) if row and row[0] is not None else 0.0
    return _stock_disponible(stock_mov, inventario_stock)


def productos_bodega_con_stock(demo, conn) -> list[dict]:
    """Productos inventario Espino con stock disponible (LC ingreso, salidas manuales)."""
    stock_map = _stock_cc_map(conn)
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(stock, 0) AS stock_inv, "
        "COALESCE(unidad_medida, ?) AS um FROM inventario ORDER BY producto",
        conn,
        params=(demo.DEFAULT_UNIDAD_INSUMO,),
    )
    out = []
    for _, r in dfi.iterrows():
        pid = int(r["id"])
        stock = _stock_disponible(stock_map.get(pid, 0.0), float(r["stock_inv"] or 0))
        if stock <= 0:
            continue
        out.append(
            {
                "id": pid,
                "producto": r["producto"],
                "stock_fmt": demo.f_cantidad(stock),
                "um": r["um"],
            }
        )
    return out


def _stock_rows(demo, dfs_view: pd.DataFrame, stock_map: dict[int, float]) -> list[dict]:
    rows = []
    for _, r in dfs_view.iterrows():
        pid = int(r["id"])
        stock_cc = _stock_disponible(stock_map.get(pid, 0.0), float(r.get("stock_inv") or 0))
        rows.append(
            {
                "producto": r["producto"],
                "ing_activo": r.get("ingrediente_activo", ""),
                "familia": r.get("familia", ""),
                "stock": demo.f_cantidad(stock_cc),
                "um": r.get("unidad_medida", "kg"),
                "pmp": demo.f_peso(r.get("precio_medio") or 0),
            }
        )
    return rows


def gather_bodega_stock(demo, conn) -> dict:
    stock_map = _stock_cc_map(conn)
    dfs = pd.read_sql_query(
        """SELECT id, producto, familia, COALESCE(stock, 0) AS stock_inv,
                  COALESCE(unidad_medida, 'kg') AS unidad_medida,
                  precio_medio, COALESCE(ingrediente_activo,'') AS ingrediente_activo
           FROM inventario ORDER BY producto COLLATE NOCASE""",
        conn,
    )
    dfs["stock_cc"] = dfs.apply(
        lambda r: _stock_disponible(stock_map.get(int(r["id"]), 0.0), float(r["stock_inv"] or 0)),
        axis=1,
    )
    q = (request.args.get("q") or "").strip()
    dfs_view = dfs.copy()
    if q:
        ql = q.lower()
        dfs_view = dfs_view[
            dfs_view["producto"].astype(str).str.lower().str.contains(ql, na=False)
            | dfs_view["familia"].astype(str).str.lower().str.contains(ql, na=False)
            | dfs_view["ingrediente_activo"].astype(str).str.lower().str.contains(ql, na=False)
        ]

    pdf_url = None
    dfs_pdf = dfs_view[dfs_view["stock_cc"].fillna(0) > 0].copy()
    if not dfs_pdf.empty:
        dfs_op = dfs_pdf.copy()
        dfs_op["stock"] = dfs_op["stock_cc"]
        dfs_op = dfs_op.drop(columns=["precio_medio", "id", "stock_cc"], errors="ignore").rename(
            columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"}
        )
        estilo = getattr(demo, "_pdf_estilo_stock_pppl", None)
        blob = demo.generar_pdf_blob(
            dfs_op,
            f"STOCK BODEGA {ETIQUETA_BODEGA} — CON STOCK (SIN PRECIOS)",
            incluir_precios=False,
            estilo_celda_fn=estilo,
        )
        if blob:
            pdf_url = url_for(
                "modules.pdf_download",
                token=store_pdf(blob, PDF_STOCK_FILENAME),
            )

    return {
        "stock_rows": _stock_rows(demo, dfs_view, stock_map),
        "stock_cols": ["producto", "ing_activo", "familia", "stock", "um", "pmp"],
        "filtro_q": q,
        "pdf_stock_url": pdf_url,
        "pdf_stock_filename": PDF_STOCK_FILENAME if pdf_url else None,
    }


def _productos_con_stock(demo, conn) -> list[dict]:
    rows = productos_bodega_con_stock(demo, conn)
    return [
        {
            "id": r["id"],
            "producto": r["producto"],
            "unidad_medida": r["um"],
            "stock_fmt": r["stock_fmt"],
        }
        for r in rows
    ]


def _productos_todos(demo, conn) -> list[dict]:
    stock_map = _stock_cc_map(conn)
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(stock, 0) AS stock_inv, "
        "COALESCE(unidad_medida, 'kg') AS unidad_medida FROM inventario ORDER BY producto",
        conn,
    )
    return [
        {
            "id": int(r["id"]),
            "producto": r["producto"],
            "unidad_medida": r["unidad_medida"],
            "stock_fmt": demo.f_cantidad(
                _stock_disponible(stock_map.get(int(r["id"]), 0.0), float(r["stock_inv"] or 0))
            ),
        }
        for _, r in dfi.iterrows()
    ]


def _bodega_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "stock").strip().lower()
    if op not in {k for k, _ in BODEGA_OPS}:
        op = "stock"
    return op


def gather_bodega(demo, conn, op_override: str | None = None) -> dict:
    op = op_override or _bodega_op_activa()
    ctx = {
        "bodega_ops": BODEGA_OPS,
        "op_activa": op,
        "productos_ingreso": _productos_todos(demo, conn),
        "productos_salida": _productos_con_stock(demo, conn),
        "familias_prod": demo.listar_familias_producto(conn),
        "unidades_medida": demo.UNIDADES_MEDIDA_INSUMO,
        "um_default": demo.DEFAULT_UNIDAD_INSUMO,
        "cc_espino": ETIQUETA_BODEGA,
    }
    ctx.update(gather_bodega_stock(demo, conn))
    return ctx


def _producto_por_id(conn, demo, iid: int):
    return conn.execute(
        "SELECT id, producto, precio_medio, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()


def _producto_por_nombre(conn, demo, nombre: str):
    return conn.execute(
        "SELECT id, producto, precio_medio, COALESCE(unidad_medida, ?) FROM inventario WHERE UPPER(producto)=?",
        (demo.DEFAULT_UNIDAD_INSUMO, nombre.upper().strip()),
    ).fetchone()


def validar_salida_bodega(
    demo,
    conn,
    cantidad: float,
    *,
    producto_id: int | None = None,
    producto: str | None = None,
) -> tuple[bool, str, int | None, str | None, str | None]:
    """Valida salida sin escribir. Retorna ok, msg, producto_id, nombre, um."""
    if cantidad <= 0:
        return False, "La cantidad debe ser mayor a cero.", None, None, None
    if producto_id:
        row = _producto_por_id(conn, demo, producto_id)
    elif producto:
        row = _producto_por_nombre(conn, demo, producto)
    else:
        return False, "Producto no indicado.", None, None, None
    if not row:
        return False, "Producto no encontrado.", None, None, None
    iid, prod_nombre, _pmp, um_sel = int(row[0]), row[1], float(row[2] or 0), row[3]
    inv_st = conn.execute("SELECT COALESCE(stock, 0) FROM inventario WHERE id=?", (iid,)).fetchone()
    stock = _stock_cc(conn, iid, inventario_stock=float(inv_st[0] if inv_st else 0))
    if cantidad > stock + 1e-9:
        return False, (
            f"Stock insuficiente de {prod_nombre} "
            f"(disponible: {demo.f_cantidad(stock)} {um_sel})."
        ), None, None, None
    return True, "", iid, prod_nombre, um_sel


def registrar_salida_bodega(
    demo,
    conn,
    cantidad: float,
    *,
    producto_id: int | None = None,
    producto: str | None = None,
    fecha=None,
) -> tuple[bool, str]:
    """Registra salida en bodega El Espino (sin commit). Usado por LC y formulario manual."""
    ok, msg, iid, prod_nombre, _um = validar_salida_bodega(
        demo, conn, cantidad, producto_id=producto_id, producto=producto
    )
    if not ok:
        return False, msg
    row = _producto_por_id(conn, demo, iid)
    pmp, um_sel = float(row[2] or 0), row[3]
    fecha_mov = str(fecha or hoy_demo(demo))
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (iid, "Salida", cantidad, fecha_mov, CC_ESPINO, cantidad * pmp, um_sel),
    )
    return True, prod_nombre


def post_salida(demo, conn) -> dict:
    try:
        iid = int(request.form.get("producto_id") or 0)
        ct = float(request.form.get("cantidad") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos de salida inválidos."}
    ok, res = registrar_salida_bodega(demo, conn, ct, producto_id=iid)
    if not ok:
        return {"ok": False, "msg": res}
    conn.commit()
    prod_nombre = res
    um = conn.execute(
        "SELECT COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()[0]
    demo.registrar_accion(CC_ESPINO, f"Salida manual bodega {prod_nombre} {demo.f_cantidad(ct)} {um}")
    return {
        "ok": True,
        "msg": f"Salida registrada: −{demo.f_cantidad(ct)} {um} de {prod_nombre}.",
        "extra": {"op": "stock"},
    }


def gather_bodega_mov(demo, conn) -> dict:
    """Alias retrocompatible."""
    return gather_bodega(demo, conn)


def post_ingreso_existente(demo, conn) -> dict:
    try:
        iid = int(request.form.get("producto_id") or 0)
        ct = float(request.form.get("cantidad") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos de ingreso inválidos."}
    if ct <= 0:
        return {"ok": False, "msg": "La cantidad debe ser mayor a cero."}

    row = conn.execute(
        "SELECT producto, precio_medio, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Producto no encontrado."}
    prod_nombre, pmp, um_sel = row[0], float(row[1] or 0), row[2]
    fecha = str(hoy_demo(demo))
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (iid, "Ingreso", ct, fecha, CC_ESPINO, ct * pmp, um_sel),
    )
    conn.commit()
    demo.registrar_accion(CC_ESPINO, f"Ingreso bodega {prod_nombre} +{demo.f_cantidad(ct)} {um_sel}")
    return {
        "ok": True,
        "msg": f"Entrada registrada: +{demo.f_cantidad(ct)} {um_sel} de {prod_nombre}.",
        "extra": {"op": "stock"},
    }


def post_ingreso_nuevo(demo, conn) -> dict:
    np = (request.form.get("nombre") or "").strip()
    nf = (request.form.get("familia") or "").strip()
    nu = request.form.get("unidad_medida") or demo.DEFAULT_UNIDAD_INSUMO
    nia = (request.form.get("ingrediente_activo") or "").strip()
    try:
        ns = float(request.form.get("stock") or 0)
        npr = float(request.form.get("precio_medio") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Stock o PMP inválido."}
    if not np:
        return {"ok": False, "msg": "Ingrese el nombre del producto."}
    if not nf:
        return {"ok": False, "msg": "Seleccione la familia del producto."}
    if not nia:
        return {"ok": False, "msg": "Indique el ingrediente activo."}
    if ns < 0:
        return {"ok": False, "msg": "El stock inicial no puede ser negativo."}
    if conn.execute("SELECT id FROM inventario WHERE UPPER(producto)=?", (np.upper(),)).fetchone():
        return {"ok": False, "msg": "El producto ya existe. Consulte stock en Bodega."}

    cur = conn.execute(
        "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida, ingrediente_activo) VALUES (?,?,?,?,?,?)",
        (np, nf, 0, npr, nu, nia),
    )
    new_id = cur.lastrowid
    req_pppl = getattr(demo, "requiere_autorizacion_pppl", None)
    if req_pppl and req_pppl(nf):
        gap = conn.execute(
            "SELECT id FROM gap_pppl WHERE UPPER(TRIM(producto))=?",
            (np.upper(),),
        ).fetchone()
        if gap:
            conn.execute(
                "UPDATE gap_pppl SET ingrediente_activo=?, vigente=1 WHERE id=?",
                (nia, gap[0]),
            )

    fecha = str(hoy_demo(demo))
    if ns > 0:
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id, "Ingreso", ns, fecha, CC_ESPINO, ns * npr, nu),
        )
    conn.commit()
    demo.registrar_accion(CC_ESPINO, f"Apertura bodega {np} stock_espino={ns}")
    extra = {"op": "stock" if ns > 0 else "nuevo"}
    if ns > 0:
        return {"ok": True, "msg": f"Producto {np} creado con stock El Espino {demo.f_cantidad(ns)} {nu}.", "extra": extra}
    return {
        "ok": True,
        "msg": f"Producto {np} creado (stock El Espino en cero).",
        "extra": extra,
    }


def post_ingreso(demo, conn) -> dict:
    modo = (request.form.get("modo") or "existente").strip()
    if modo == "nuevo":
        return post_ingreso_nuevo(demo, conn)
    return post_ingreso_existente(demo, conn)
