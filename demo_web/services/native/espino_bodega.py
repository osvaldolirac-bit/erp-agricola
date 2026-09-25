"""Bodega sector El Espino — stock por CC del huerto, sin alterar inventario global ni La Concepción."""
from __future__ import annotations

import sqlite3

import pandas as pd
from flask import request, url_for

from demo_web.services.espino_compras_kardex import origen_compra_ingreso
from demo_web.services.espino_scope import (
    BODEGA_CC_ESPINO,
    CC_MOVIMIENTOS_BODEGA_ESPINO,
    centros_costo_bodega_espino,
    es_cuartel_espino,
    normalizar_cuartel_espino,
)
from demo_web.services.module_runner import store_pdf
from demo_web.services.native._helpers import hoy_demo

# CC en nuevos movimientos; etiqueta UI = BODEGA_CC_ESPINO.
CC_ESPINO = CC_MOVIMIENTOS_BODEGA_ESPINO
ETIQUETA_BODEGA = BODEGA_CC_ESPINO

PDF_STOCK_FILENAME = "STOCK_BODEGA_EL_ESPINO.pdf"


def _pdf_filename_producto(nombre: str, prefix: str = "KARDEX") -> str:
    safe = "".join(c if c.isalnum() else "_" for c in (nombre or "PRODUCTO").upper())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return f"{prefix}_{safe.strip('_')[:48]}.pdf"


def _pdf_kardex_producto(demo, prod: dict, rows: list[dict]) -> tuple[str | None, str | None]:
    um = prod["um"]
    titulo = (
        f"CUENTA CORRIENTE BODEGA — {prod['nombre']} | "
        f"Stock {prod['stock']} {um} | Ing {prod['ing_total']} {um} | Sal {prod['sal_total']} {um}"
    )
    if rows:
        df = pd.DataFrame(
            [
                {
                    "FECHA": r["fecha"],
                    "TIPO": r["tipo"],
                    "CANTIDAD": r["cant_raw"] if r["tipo"] == "Ingreso" else -r["cant_raw"],
                    "UM": um,
                    "CUARTEL": r["cuartel"],
                    "ORIGEN": r["origen"],
                    "SALDO": r["saldo_raw"],
                }
                for r in rows
            ]
        )
    else:
        df = pd.DataFrame(
            [{"DETALLE": f"Sin movimientos. Stock actual: {prod['stock']} {um}"}]
        )
    fname = _pdf_filename_producto(prod["nombre"])
    blob = demo.generar_pdf_blob(df, titulo, incluir_precios=False)
    if not blob:
        return None, None
    return url_for("modules.pdf_download", token=store_pdf(blob, fname)), fname

BODEGA_SECCIONES = [
    ("bodega", "📦 BODEGA"),
]

BODEGA_OPS = [
    ("stock", "📊 Stock actual"),
    ("nuevo", "➕ Crear producto"),
]

_BODEGA_OPS_VALID = {k for k, _ in BODEGA_OPS} | {"kardex"}


def bodega_secciones() -> list[tuple[str, str]]:
    return list(BODEGA_SECCIONES)


def _es_producto_bodega_espino(nombre: str) -> bool:
    """Todo el inventario del tenant Espino pertenece a su bodega."""
    _ = nombre
    return True


def _cc_pool_bodega_sql() -> tuple[str, tuple[str, ...]]:
    ccs = sorted(centros_costo_bodega_espino())
    return ",".join("?" * len(ccs)), tuple(ccs)


def _ingresos_pool(conn, producto_id: int) -> float:
    ph, ccs = _cc_pool_bodega_sql()
    row = conn.execute(
        f"""SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
            WHERE producto_id=? AND tipo='Ingreso' AND UPPER(centro_costo) IN ({ph})""",
        (producto_id, *ccs),
    ).fetchone()
    return float(row[0] or 0)


def _salidas_totales(conn, producto_id: int) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(cantidad), 0) FROM movimientos
           WHERE producto_id=? AND tipo='Salida'""",
        (producto_id,),
    ).fetchone()
    return float(row[0] or 0)


def _stock_esperado_kardex(conn, producto_id: int) -> float | None:
    """Stock teórico desde kardex bodega (ingresos pool − salidas). None si no hay ingresos kardex."""
    ing = _ingresos_pool(conn, producto_id)
    if ing <= 1e-9:
        return None
    return max(ing - _salidas_totales(conn, producto_id), 0.0)


def _sync_inventario_stock(conn, producto_id: int) -> float:
    """Mantiene inventario.stock alineado con kardex cuando hay ingresos pool."""
    row = conn.execute("SELECT COALESCE(stock, 0) FROM inventario WHERE id=?", (producto_id,)).fetchone()
    stock = float(row[0] or 0) if row else 0.0
    esperado = _stock_esperado_kardex(conn, producto_id)
    if esperado is None:
        return max(stock, 0.0)
    if abs(esperado - stock) > 1e-6:
        conn.execute("UPDATE inventario SET stock=? WHERE id=?", (esperado, producto_id))
    return esperado


def _stock_disponible_producto(conn, producto_id: int, *, inventario_stock: float | None = None) -> float:
    """Stock bodega: kardex (ing−sal) si hay ingresos pool; si no, inventario.stock."""
    if inventario_stock is None:
        row = conn.execute("SELECT COALESCE(stock, 0) FROM inventario WHERE id=?", (producto_id,)).fetchone()
        inventario_stock = float(row[0] or 0) if row else 0.0
    esperado = _stock_esperado_kardex(conn, producto_id)
    if esperado is not None:
        return esperado
    return max(float(inventario_stock or 0), 0.0)


def _precio_medio_kardex(conn: sqlite3.Connection, producto_id: int) -> float | None:
    """PMP ponderado desde ingresos pool bodega (más fiable que inventario.precio_medio)."""
    ph, ccs = _cc_pool_bodega_sql()
    row = conn.execute(
        f"""SELECT COALESCE(SUM(valor_imputado), 0), COALESCE(SUM(cantidad), 0)
            FROM movimientos
            WHERE producto_id=? AND tipo='Ingreso'
              AND UPPER(TRIM(centro_costo)) IN ({ph})""",
        (producto_id, *ccs),
    ).fetchone()
    if not row or float(row[1] or 0) <= 1e-9:
        return None
    return float(row[0]) / float(row[1])


def _stock_cc_map(conn) -> dict[int, float]:
    """Stock disponible por producto (bodega El Espino)."""
    out: dict[int, float] = {}
    for (pid,) in conn.execute("SELECT id FROM inventario").fetchall():
        out[int(pid)] = _stock_disponible_producto(conn, int(pid))
    return out


def _stock_cc(conn, producto_id: int, *, inventario_stock: float = 0.0) -> float:
    return _stock_disponible_producto(conn, producto_id, inventario_stock=inventario_stock)


def _normalizar_cc_salida(centro_costo: str | None) -> str:
    cc = normalizar_cuartel_espino(centro_costo or "")
    if cc:
        return cc
    raw = (centro_costo or "").strip()
    if raw and es_cuartel_espino(raw):
        return normalizar_cuartel_espino(raw)
    return CC_MOVIMIENTOS_BODEGA_ESPINO


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
        stock = stock_map.get(pid, 0.0)
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
        stock_cc = stock_map.get(pid, 0.0)
        rows.append(
            {
                "id": pid,
                "producto": r["producto"],
                "ing_activo": r.get("ingrediente_activo", ""),
                "familia": r.get("familia", ""),
                "stock": demo.f_cantidad(stock_cc),
                "um": r.get("unidad_medida", "kg"),
                "pmp": demo.f_peso(r.get("precio_medio") or 0),
            }
        )
    return rows


def _lc_lineas_producto(conn, producto: str) -> list[dict]:
    rows = conn.execute(
        """SELECT n_aplicacion, fecha, sector, gasto_total
           FROM libro_campo WHERE UPPER(TRIM(producto))=?
           ORDER BY CAST(n_aplicacion AS INTEGER), id""",
        (producto.upper().strip(),),
    ).fetchall()
    return [
        {
            "n_app": int(r[0] or 0),
            "fecha": str(r[1] or ""),
            "sector": str(r[2] or ""),
            "gasto": float(r[3] or 0),
            "_used": False,
        }
        for r in rows
    ]


def _sector_coincide(sector: str, centro_costo: str) -> bool:
    sec_u = (sector or "").strip().upper()
    cc_u = (centro_costo or "").strip().upper()
    if not sec_u or not cc_u:
        return False
    if sec_u == cc_u:
        return True
    nv = normalizar_cuartel_espino(sector)
    nc = normalizar_cuartel_espino(centro_costo)
    if nv and nc and nv == nc:
        return True
    return sec_u in cc_u or cc_u in sec_u


def _normalize_tipo_mov(tipo: str) -> str:
    t = (tipo or "").strip().lower()
    if t.startswith("ing") or t.startswith("entr"):
        return "Ingreso"
    if t.startswith("sal"):
        return "Salida"
    return (tipo or "").strip() or "Salida"


def _origen_movimiento(
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    tipo: str,
    cant: float,
    fecha: str,
    centro_costo: str,
    lc_lineas: list[dict],
) -> str:
    if _normalize_tipo_mov(tipo) == "Ingreso":
        origen = origen_compra_ingreso(conn, producto_id, producto_nombre, cant, fecha)
        if origen:
            return origen
        cc = (centro_costo or "").strip()
        if cc and cc.upper() not in {c.upper() for c in centros_costo_bodega_espino()}:
            return f"Ingreso manual → {cc}"
        return "Ingreso bodega"
    for lc in lc_lineas:
        if lc.get("_used"):
            continue
        if str(lc["fecha"]) != str(fecha):
            continue
        if abs(float(lc["gasto"]) - cant) > 1e-4:
            continue
        if not _sector_coincide(lc["sector"], centro_costo):
            continue
        lc["_used"] = True
        return f"LC App N° {lc['n_app']:05d}"
    cc = normalizar_cuartel_espino(centro_costo) or (centro_costo or "").strip() or "—"
    return f"Salida manual → {cc}"


def _kardex_row(
    demo,
    *,
    row_id: int,
    fecha: str,
    tipo: str,
    qty: float,
    cuartel: str,
    origen: str,
    saldo: float,
) -> dict:
    tipo_n = _normalize_tipo_mov(tipo)
    delta = qty if tipo_n == "Ingreso" else -qty
    return {
        "id": row_id,
        "fecha": fecha,
        "tipo": tipo_n,
        "cantidad": demo.f_cantidad(qty),
        "cant_raw": qty,
        "delta_fmt": ("+" if delta >= 0 else "−") + demo.f_cantidad(abs(delta)),
        "cuartel": cuartel,
        "origen": origen,
        "saldo": demo.f_cantidad(saldo),
        "saldo_raw": saldo,
    }


def _recalc_kardex_saldos(demo, rows: list[dict]) -> None:
    saldo = 0.0
    for r in rows:
        delta = r["cant_raw"] if r["tipo"] == "Ingreso" else -r["cant_raw"]
        saldo += delta
        r["saldo"] = demo.f_cantidad(saldo)
        r["saldo_raw"] = saldo


def _build_kardex_rows(
    demo,
    conn: sqlite3.Connection,
    producto_id: int,
    producto_nombre: str,
    movs: list[tuple],
    lc_lineas: list[dict],
    *,
    stock_objetivo: float | None = None,
) -> list[dict]:
    """Arma filas kardex desde movimientos; agrega apertura si el stock no cuadra."""
    rows: list[dict] = []
    for mid, tipo, cant, fecha, cc in movs:
        tipo_n = _normalize_tipo_mov(str(tipo))
        qty = float(cant or 0)
        rows.append(
            _kardex_row(
                demo,
                row_id=int(mid),
                fecha=str(fecha or ""),
                tipo=tipo_n,
                qty=qty,
                cuartel=(cc or "").strip() or "—",
                origen=_origen_movimiento(
                    conn,
                    producto_id,
                    producto_nombre,
                    str(tipo),
                    qty,
                    str(fecha or ""),
                    str(cc or ""),
                    lc_lineas,
                ),
                saldo=0.0,
            )
        )

    if stock_objetivo is not None:
        ing = sum(r["cant_raw"] for r in rows if r["tipo"] == "Ingreso")
        sal = sum(r["cant_raw"] for r in rows if r["tipo"] == "Salida")
        apertura = float(stock_objetivo) - ing + sal
        if apertura > 1e-6:
            rows.insert(
                0,
                _kardex_row(
                    demo,
                    row_id=0,
                    fecha="—",
                    tipo="Ingreso",
                    qty=apertura,
                    cuartel=ETIQUETA_BODEGA,
                    origen="Stock inicial / apertura",
                    saldo=0.0,
                ),
            )

    _recalc_kardex_saldos(demo, rows)
    return rows


def gather_kardex_producto(demo, conn, producto_id: int) -> dict:
    """Libro mayor bodega: movimientos + saldo acumulado + enlace LC."""
    row = conn.execute(
        """SELECT id, producto, familia, COALESCE(unidad_medida, ?), COALESCE(stock, 0),
                  COALESCE(ingrediente_activo, '')
           FROM inventario WHERE id=?""",
        (demo.DEFAULT_UNIDAD_INSUMO, producto_id),
    ).fetchone()
    if not row:
        return {"kardex_error": "Producto no encontrado."}

    pid, nombre, familia, um, _inv, ing_act = (
        int(row[0]),
        row[1],
        row[2],
        row[3],
        float(row[4] or 0),
        row[5],
    )
    lc_lineas = _lc_lineas_producto(conn, nombre)
    movs = conn.execute(
        """SELECT id, tipo, cantidad, fecha, centro_costo
           FROM movimientos WHERE producto_id=?
           ORDER BY fecha, id""",
        (pid,),
    ).fetchall()

    stock_ui = _stock_disponible_producto(conn, pid)
    kardex_rows = _build_kardex_rows(
        demo, conn, pid, nombre, movs, lc_lineas, stock_objetivo=stock_ui
    )
    lc_sin_par = [lc for lc in lc_lineas if not lc.get("_used")]

    ing_total = sum(r["cant_raw"] for r in kardex_rows if r["tipo"] == "Ingreso")
    sal_total = sum(r["cant_raw"] for r in kardex_rows if r["tipo"] == "Salida")

    kardex_producto = {
        "id": pid,
        "nombre": nombre,
        "familia": familia,
        "um": um,
        "ing_activo": ing_act,
        "stock": demo.f_cantidad(stock_ui),
        "ing_total": demo.f_cantidad(ing_total),
        "sal_total": demo.f_cantidad(sal_total),
    }
    pdf_kardex_url, pdf_kardex_filename = _pdf_kardex_producto(demo, kardex_producto, kardex_rows)

    return {
        "kardex_producto": kardex_producto,
        "kardex_rows": kardex_rows,
        "pdf_kardex_url": pdf_kardex_url,
        "pdf_kardex_filename": pdf_kardex_filename,
        "kardex_lc_pendientes": [
            {
                "n_app": lc["n_app"],
                "fecha": lc["fecha"],
                "sector": lc["sector"],
                "gasto": demo.f_cantidad(lc["gasto"]),
            }
            for lc in lc_sin_par
        ],
    }


def gather_bodega_stock(demo, conn) -> dict:
    stock_map = _stock_cc_map(conn)
    dfs = pd.read_sql_query(
        """SELECT id, producto, familia, COALESCE(stock, 0) AS stock_inv,
                  COALESCE(unidad_medida, 'kg') AS unidad_medida,
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
        # Numérico para PDF: f_cantidad se aplica en generar_pdf_blob (evita doble formato "2,25"→0).
        dfs_op["stock"] = dfs_op["stock_cc"].astype(float)
        dfs_op = dfs_op.drop(columns=["precio_medio", "id", "stock_inv", "stock_cc"], errors="ignore").rename(
            columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"}
        )
        estilo = getattr(demo, "_pdf_estilo_stock_pppl", None)
        blob = demo.generar_pdf_blob(
            dfs_op,
            f"STOCK BODEGA {ETIQUETA_BODEGA} — TODOS LOS PRODUCTOS (SIN PRECIOS)",
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
            "stock_fmt": demo.f_cantidad(stock_map.get(int(r["id"]), 0.0)),
        }
        for _, r in dfi.iterrows()
    ]


def _bodega_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "stock").strip().lower()
    if op not in _BODEGA_OPS_VALID:
        op = "stock"
    return op


def _kardex_producto_id() -> int:
    raw = (request.args.get("pid") or request.args.get("producto_id") or "0").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


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
    if op == "kardex":
        pid = _kardex_producto_id()
        if pid:
            ctx.update(gather_kardex_producto(demo, conn, pid))
        else:
            ctx["kardex_error"] = "Seleccione un producto desde el listado de stock."
        return ctx
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


def _bootstrap_kardex_apertura(
    demo,
    conn,
    producto_id: int,
    *,
    fecha: str | None = None,
) -> bool:
    """Crea ingreso de apertura desde inventario.stock si el kardex no tiene movimientos."""
    if _ingresos_pool(conn, producto_id) > 1e-9:
        return False
    row = conn.execute(
        """SELECT COALESCE(stock, 0), COALESCE(precio_medio, 0),
                  COALESCE(unidad_medida, ?)
           FROM inventario WHERE id=?""",
        (demo.DEFAULT_UNIDAD_INSUMO, producto_id),
    ).fetchone()
    if not row or float(row[0] or 0) <= 1e-9:
        return False
    stock, pmp, um = float(row[0]), float(row[1] or 0), row[2]
    if pmp <= 0:
        return False
    fecha_mov = str(fecha or hoy_demo(demo))
    valor = round(stock * pmp, 2)
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?, 'Ingreso', ?, ?, ?, ?, ?)""",
        (producto_id, stock, fecha_mov, CC_ESPINO, valor, um),
    )
    _sync_inventario_stock(conn, producto_id)
    return True


def validar_salida_bodega(
    demo,
    conn,
    cantidad: float,
    *,
    producto_id: int | None = None,
    producto: str | None = None,
) -> tuple[bool, str, int | None, str | None, str | None]:
    """Valida salida; crea ingreso apertura en kardex si hay stock sin movimientos previos."""
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
    inv_stock = float(inv_st[0] if inv_st else 0)
    if _ingresos_pool(conn, iid) <= 1e-9 and inv_stock > 1e-9:
        if not _bootstrap_kardex_apertura(demo, conn, iid):
            return (
                False,
                f"{prod_nombre}: hay stock en bodega pero falta kardex de apertura "
                f"(registre ingreso en Bodega o indique PMP en inventario).",
                None,
                None,
                None,
            )
    stock = _stock_disponible_producto(conn, iid, inventario_stock=inv_stock)
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
    centro_costo: str | None = None,
) -> tuple[bool, str]:
    """Registra salida en bodega El Espino (sin commit). Imputa al cuartel/variedad indicado."""
    ok, msg, iid, prod_nombre, _um = validar_salida_bodega(
        demo, conn, cantidad, producto_id=producto_id, producto=producto
    )
    if not ok:
        return False, msg
    row = _producto_por_id(conn, demo, iid)
    um_sel = row[3]
    pmp = _precio_medio_kardex(conn, iid)
    if pmp is None:
        pmp = float(row[2] or 0)
    fecha_mov = str(fecha or hoy_demo(demo))
    cc_imputacion = _normalizar_cc_salida(centro_costo)
    valor = round(float(cantidad) * pmp, 2)
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (iid, "Salida", cantidad, fecha_mov, cc_imputacion, valor, um_sel),
    )
    if _stock_esperado_kardex(conn, iid) is not None:
        _sync_inventario_stock(conn, iid)
    else:
        conn.execute(
            "UPDATE inventario SET stock = MAX(COALESCE(stock, 0) - ?, 0) WHERE id=?",
            (cantidad, iid),
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
    if _stock_esperado_kardex(conn, iid) is not None:
        _sync_inventario_stock(conn, iid)
    else:
        conn.execute(
            "UPDATE inventario SET stock = COALESCE(stock, 0) + ? WHERE id=?",
            (ct, iid),
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
    if ns > 0 and npr <= 0:
        return {
            "ok": False,
            "msg": "Indique precio medio (PMP) al abrir stock; es necesario para imputar salidas al CC.",
        }
    if conn.execute("SELECT id FROM inventario WHERE UPPER(producto)=?", (np.upper(),)).fetchone():
        return {"ok": False, "msg": "El producto ya existe. Consulte stock en Bodega."}

    cur = conn.execute(
        "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida, ingrediente_activo) VALUES (?,?,?,?,?,?)",
        (np, nf, ns if ns > 0 else 0, npr, nu, nia),
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
        _sync_inventario_stock(conn, int(new_id))
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
