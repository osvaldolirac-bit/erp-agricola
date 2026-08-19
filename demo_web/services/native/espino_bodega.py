"""Bodega sector El Espino — stock, ingreso y salida (inventario compartido, CC fijo)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import request, session, url_for

from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

CC_ESPINO = "EL ESPINO"

BODEGA_SECCIONES = [
    ("bodega_stock", "📊 STOCK"),
    ("bodega_ingreso", "📥 INGRESO"),
    ("bodega_salida", "🔄 SALIDA"),
]


def bodega_secciones() -> list[tuple[str, str]]:
    return list(BODEGA_SECCIONES)


def _stock_rows(demo, dfs_view: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in dfs_view.iterrows():
        rows.append(
            {
                "producto": r["producto"],
                "ing_activo": r.get("ingrediente_activo", ""),
                "familia": r.get("familia", ""),
                "stock": demo.f_cantidad(r["stock"]),
                "um": r.get("unidad_medida", "kg"),
                "pmp": demo.f_peso(r.get("precio_medio") or 0),
            }
        )
    return rows


def gather_bodega_stock(demo, conn) -> dict:
    dfs = pd.read_sql_query(
        """SELECT id, producto, familia, stock, COALESCE(unidad_medida, 'kg') AS unidad_medida,
                  precio_medio, COALESCE(ingrediente_activo,'') AS ingrediente_activo
           FROM inventario ORDER BY producto COLLATE NOCASE""",
        conn,
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
    if not dfs_view.empty:
        dfs_op = dfs_view.drop(columns=["precio_medio", "id"], errors="ignore").rename(
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
        "stock_rows": _stock_rows(demo, dfs_view),
        "stock_cols": ["producto", "ing_activo", "familia", "stock", "um", "pmp"],
        "filtro_q": q,
        "pdf_stock_url": pdf_url,
    }


def _productos_con_stock(demo, conn) -> list[dict]:
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(unidad_medida, 'kg') AS unidad_medida, stock "
        "FROM inventario WHERE stock > 0 ORDER BY producto",
        conn,
    )
    return [
        {
            "id": int(r["id"]),
            "producto": r["producto"],
            "unidad_medida": r["unidad_medida"],
            "stock_fmt": demo.f_cantidad(r["stock"]),
        }
        for _, r in dfi.iterrows()
    ]


def _productos_todos(demo, conn) -> list[dict]:
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(unidad_medida, 'kg') AS unidad_medida, stock "
        "FROM inventario ORDER BY producto",
        conn,
    )
    return [
        {
            "id": int(r["id"]),
            "producto": r["producto"],
            "unidad_medida": r["unidad_medida"],
            "stock_fmt": demo.f_cantidad(r["stock"]),
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


def gather_bodega_ingreso(demo, conn) -> dict:
    rows, pdf_url = _movimientos_cc(demo, conn, "Ingreso")
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)
    return {
        "productos_ingreso": _productos_todos(demo, conn),
        "familias_prod": demo.listar_familias_producto(conn),
        "unidades_medida": demo.UNIDADES_MEDIDA_INSUMO,
        "um_default": demo.DEFAULT_UNIDAD_INSUMO,
        "ingreso_rows": rows,
        "pdf_ingreso_url": pdf_url,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "modo_ingreso": request.args.get("modo", "existente"),
    }


def gather_bodega_salida(demo, conn) -> dict:
    rows, pdf_url = _movimientos_cc(demo, conn, "Salida")
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)
    alerta = session.pop("espino_bodega_alerta_lc", None)
    return {
        "productos_salida": _productos_con_stock(demo, conn),
        "salida_rows": rows,
        "pdf_salida_url": pdf_url,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "alerta_lc": alerta,
        "cc_espino": CC_ESPINO,
    }


def post_salida(demo, conn) -> dict:
    try:
        iid = int(request.form.get("producto_id") or 0)
        ct = float(request.form.get("cantidad") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos de salida inválidos."}

    row = conn.execute(
        "SELECT producto, precio_medio, stock, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Producto no encontrado."}
    prod_nombre, pmp, stock, um_sel = row[0], float(row[1] or 0), float(row[2] or 0), row[3]
    if ct <= 0:
        return {"ok": False, "msg": "Indique una cantidad válida."}
    if ct > stock + 1e-9:
        return {"ok": False, "msg": f"Stock insuficiente (disponible: {demo.f_cantidad(stock)} {um_sel})."}

    fecha = str(hoy_demo(demo))
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (iid, "Salida", ct, fecha, CC_ESPINO, ct * pmp, um_sel),
    )
    conn.execute("UPDATE inventario SET stock = stock - ? WHERE id = ?", (ct, iid))
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
    conn.execute("UPDATE inventario SET stock = stock + ? WHERE id = ?", (ct, iid))
    conn.commit()
    demo.registrar_accion(CC_ESPINO, f"Ingreso bodega {prod_nombre} +{demo.f_cantidad(ct)} {um_sel}")
    return {"ok": True, "msg": f"Ingreso registrado: +{demo.f_cantidad(ct)} {um_sel} de {prod_nombre}."}


def post_ingreso_nuevo(demo, conn) -> dict:
    np = (request.form.get("nombre") or "").strip()
    nf = request.form.get("familia") or ""
    nu = request.form.get("unidad_medida") or demo.DEFAULT_UNIDAD_INSUMO
    nia = (request.form.get("ingrediente_activo") or "").strip()
    try:
        ns = float(request.form.get("stock") or 0)
        npr = float(request.form.get("precio_medio") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Stock o PMP inválido."}
    if not np:
        return {"ok": False, "msg": "Ingrese el nombre del producto."}
    if ns <= 0:
        return {"ok": False, "msg": "Indique stock inicial mayor a cero."}
    if conn.execute("SELECT id FROM inventario WHERE UPPER(producto)=?", (np.upper(),)).fetchone():
        return {"ok": False, "msg": "El producto ya existe. Use ingreso a producto existente."}

    cur = conn.execute(
        "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida, ingrediente_activo) VALUES (?,?,?,?,?,?)",
        (np, nf, ns, npr, nu, nia),
    )
    new_id = cur.lastrowid
    if not nia:
        try:
            from erp_inventario_ia import poblar_ingredientes_inventario

            poblar_ingredientes_inventario(conn, new_id)
        except Exception:
            pass

    fecha = str(hoy_demo(demo))
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (new_id, "Ingreso", ns, fecha, CC_ESPINO, ns * npr, nu),
    )
    conn.commit()
    demo.registrar_accion(CC_ESPINO, f"Apertura bodega {np} stock={ns}")
    return {"ok": True, "msg": f"Producto {np} creado con stock inicial {demo.f_cantidad(ns)} {nu}."}


def post_ingreso(demo, conn) -> dict:
    modo = (request.form.get("modo") or "existente").strip()
    if modo == "nuevo":
        return post_ingreso_nuevo(demo, conn)
    return post_ingreso_existente(demo, conn)
