"""Bodega sector El Espino — stock, ingreso y salida (inventario compartido, CC fijo)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import request, session, url_for

from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

CC_ESPINO = "EL ESPINO"

BODEGA_SECCIONES = [
    ("bodega", "📦 BODEGA"),
]

BODEGA_OPS = [
    ("ingreso", "📥 Ingreso"),
    ("stock", "📊 Stock"),
    ("salida", "🔄 Salida"),
    ("nuevo", "➕ Crear producto"),
]


def bodega_secciones() -> list[tuple[str, str]]:
    return list(BODEGA_SECCIONES)


def _stock_cc_map(conn) -> dict[int, float]:
    """Stock imputado solo a EL ESPINO (ingresos − salidas). No usa inventario.stock global."""
    rows = conn.execute(
        """SELECT producto_id,
                  SUM(CASE WHEN tipo = 'Ingreso' THEN cantidad ELSE -cantidad END) AS stock_cc
           FROM movimientos
           WHERE centro_costo = ?
           GROUP BY producto_id""",
        (CC_ESPINO,),
    ).fetchall()
    return {int(r[0]): float(r[1] or 0) for r in rows}


def _stock_cc(conn, producto_id: int) -> float:
    row = conn.execute(
        """SELECT SUM(CASE WHEN tipo = 'Ingreso' THEN cantidad ELSE -cantidad END)
           FROM movimientos WHERE centro_costo = ? AND producto_id = ?""",
        (CC_ESPINO, producto_id),
    ).fetchone()
    return float(row[0] or 0) if row and row[0] is not None else 0.0


def _stock_rows(demo, dfs_view: pd.DataFrame, stock_map: dict[int, float]) -> list[dict]:
    rows = []
    for _, r in dfs_view.iterrows():
        pid = int(r["id"])
        stock_cc = stock_map.get(pid, 0.0)
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
        """SELECT id, producto, familia, COALESCE(unidad_medida, 'kg') AS unidad_medida,
                  precio_medio, COALESCE(ingrediente_activo,'') AS ingrediente_activo
           FROM inventario ORDER BY producto COLLATE NOCASE""",
        conn,
    )
    dfs["stock_cc"] = dfs["id"].map(lambda i: stock_map.get(int(i), 0.0))
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
    if not dfs_view.empty:
        dfs_op = dfs_view.copy()
        dfs_op["stock"] = dfs_op["stock_cc"]
        dfs_op = dfs_op.drop(columns=["precio_medio", "id", "stock_cc"], errors="ignore").rename(
            columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"}
        )
        estilo = getattr(demo, "_pdf_estilo_stock_pppl", None)
        blob = demo.generar_pdf_blob(
            dfs_op,
            f"STOCK BODEGA {CC_ESPINO} (SIN PRECIOS)",
            incluir_precios=False,
            estilo_celda_fn=estilo,
        )
        if blob:
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, "espino_stock.pdf"))

    return {
        "stock_rows": _stock_rows(demo, dfs_view, stock_map),
        "stock_cols": ["producto", "ing_activo", "familia", "stock", "um", "pmp"],
        "filtro_q": q,
        "pdf_stock_url": pdf_url,
    }


def _productos_con_stock(demo, conn) -> list[dict]:
    stock_map = _stock_cc_map(conn)
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(unidad_medida, 'kg') AS unidad_medida FROM inventario ORDER BY producto",
        conn,
    )
    out = []
    for _, r in dfi.iterrows():
        pid = int(r["id"])
        stock = stock_map.get(pid, 0.0)
        if stock <= 0:
            continue
        out.append(
            {
                "id": pid,
                "producto": r["producto"],
                "unidad_medida": r["unidad_medida"],
                "stock_fmt": demo.f_cantidad(stock),
            }
        )
    return out


def _productos_todos(demo, conn) -> list[dict]:
    stock_map = _stock_cc_map(conn)
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(unidad_medida, 'kg') AS unidad_medida FROM inventario ORDER BY producto",
        conn,
    )
    return [
        {
            "id": int(r["id"]),
            "producto": r["producto"],
            "unidad_medida": r["unidad_medida"],
            "stock_fmt": demo.f_cantidad(stock_map.get(int(r["id"]), 0.0)),
        }
        for _, r in dfi.iterrows()
    ]


def _movimientos_cc(demo, conn, tipo: str, dias: int = 90) -> tuple[list[dict], str | None]:
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=dias))
    ff = parse_date(request.args.get("hasta"), hoy)
    sql_um = demo._sql_um_movimiento()
    df = pd.read_sql_query(
        f"""SELECT m.id AS ID, m.fecha AS FECHA, i.producto AS PRODUCTO,
                   m.cantidad AS CANTIDAD, {sql_um} AS UM, m.valor_imputado AS VALOR
            FROM movimientos m JOIN inventario i ON m.producto_id = i.id
            WHERE m.centro_costo = ? AND m.tipo = ?
              AND m.fecha BETWEEN ? AND ?
            ORDER BY m.fecha DESC, m.id DESC""",
        conn,
        params=(CC_ESPINO, tipo, str(fi), str(ff)),
    )
    rows = []
    pdf_url = None
    if not df.empty:
        for _, r in df.iterrows():
            rows.append(
                {
                    "id": int(r["ID"]),
                    "fecha": str(r["FECHA"])[:10],
                    "producto": r["PRODUCTO"],
                    "cantidad": demo.f_cantidad(r["CANTIDAD"]),
                    "um": r["UM"],
                    "valor": demo.f_peso(r["VALOR"]),
                }
            )
        df_pdf = df[["FECHA", "PRODUCTO", "CANTIDAD", "UM", "VALOR"]].copy()
        titulo = f"{tipo.upper()} BODEGA {CC_ESPINO} ({fi} a {ff})"
        blob = demo.generar_pdf_blob(df_pdf, titulo)
        if blob:
            fname = f"espino_{tipo.lower()}_{CC_ESPINO.lower().replace(' ', '_')}.pdf"
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, fname))
    return rows, pdf_url


def _bodega_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "ingreso").strip().lower()
    if op not in {k for k, _ in BODEGA_OPS}:
        op = "ingreso"
    return op


def gather_bodega(demo, conn, op_override: str | None = None) -> dict:
    ingreso_rows, pdf_ingreso = _movimientos_cc(demo, conn, "Ingreso")
    salida_rows, pdf_salida = _movimientos_cc(demo, conn, "Salida")
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)
    op = op_override or _bodega_op_activa()
    ctx = {
        "bodega_ops": BODEGA_OPS,
        "op_activa": op,
        "productos_ingreso": _productos_todos(demo, conn),
        "productos_salida": _productos_con_stock(demo, conn),
        "familias_prod": demo.listar_familias_producto(conn),
        "unidades_medida": demo.UNIDADES_MEDIDA_INSUMO,
        "um_default": demo.DEFAULT_UNIDAD_INSUMO,
        "ingreso_rows": ingreso_rows,
        "salida_rows": salida_rows,
        "pdf_ingreso_url": pdf_ingreso,
        "pdf_salida_url": pdf_salida,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "alerta_lc": session.pop("espino_bodega_alerta_lc", None),
        "cc_espino": CC_ESPINO,
    }
    ctx.update(gather_bodega_stock(demo, conn))
    return ctx


def gather_bodega_mov(demo, conn) -> dict:
    """Alias retrocompatible."""
    return gather_bodega(demo, conn)


def post_salida(demo, conn) -> dict:
    try:
        iid = int(request.form.get("producto_id") or 0)
        ct = float(request.form.get("cantidad") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos de salida inválidos."}

    row = conn.execute(
        "SELECT producto, precio_medio, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Producto no encontrado."}
    prod_nombre, pmp, um_sel = row[0], float(row[1] or 0), row[2]
    stock = _stock_cc(conn, iid)
    if ct <= 0:
        return {"ok": False, "msg": "Indique una cantidad válida."}
    if ct > stock + 1e-9:
        return {"ok": False, "msg": f"Stock insuficiente en El Espino (disponible: {demo.f_cantidad(stock)} {um_sel})."}

    fecha = str(hoy_demo(demo))
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (iid, "Salida", ct, fecha, CC_ESPINO, ct * pmp, um_sel),
    )
    conn.commit()
    demo.registrar_accion(CC_ESPINO, f"Salida bodega {prod_nombre} {demo.f_cantidad(ct)} {um_sel}")

    if demo.producto_pppl_aprobado(conn, prod_nombre):
        session["espino_bodega_alerta_lc"] = {
            "producto": prod_nombre,
            "cantidad": ct,
            "um": um_sel,
            "cuarteles": [CC_ESPINO],
        }
        return {"ok": True, "msg": "Salida registrada. Revise aviso PPPL / Libro de Campo."}
    return {"ok": True, "msg": f"Salida bodega {CC_ESPINO} registrada."}


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
    return {"ok": True, "msg": f"Ingreso registrado: +{demo.f_cantidad(ct)} {um_sel} de {prod_nombre}."}


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
        return {"ok": False, "msg": "El producto ya existe. Use ingreso a producto existente."}

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
    if ns > 0:
        return {"ok": True, "msg": f"Producto {np} creado con stock El Espino {demo.f_cantidad(ns)} {nu}."}
    return {"ok": True, "msg": f"Producto {np} creado (stock El Espino en cero). Registre ingresos cuando corresponda."}


def post_ingreso(demo, conn) -> dict:
    modo = (request.form.get("modo") or "existente").strip()
    if modo == "nuevo":
        return post_ingreso_nuevo(demo, conn)
    return post_ingreso_existente(demo, conn)
