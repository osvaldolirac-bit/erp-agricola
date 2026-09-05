"""Libro de Campo sector El Espino — réplica scoped a CC EL ESPINO + bodega Espino."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import request, session, url_for

from demo_web.services.module_runner import pdf_download_url, store_pdf
from demo_web.services.native import espino_bodega
from demo_web.services.native._helpers import hoy_demo, parse_date
from demo_web.services.native.libro_campo import _ensure_maquinaria_tenant, _especies_libro_campo

CC_ESPINO = espino_bodega.CC_ESPINO
CAR_KEY = "espino_lc_car"
META_KEY = "espino_lc_evento_meta"

LIBRO_SECCIONES = [("libro_campo", "📒 LIBRO DE CAMPO")]

LIBRO_OPS = [
    ("ingreso", "📥 Ingreso aplicación"),
    ("historial", "📜 Historial"),
    ("desfase", "⚠️ Desfase bodega"),
]

UNIDADES_DOSIS = [
    "Gramos (g)",
    "Centímetros Cúbicos (cc)",
    "Kilogramos (kg)",
    "Litros (L)",
]

_N_APP_HIST_MIN = 10000

PDF_TITULO = f"LIBRO DE CAMPO {CC_ESPINO}"
PDF_FILENAME = "LIBRO_DE_CAMPO_EL_ESPINO.pdf"


def _generar_pdf_historial(demo, df) -> bytes | None:
    titulo = PDF_TITULO
    fn = demo.generar_pdf_libro_campo
    try:
        return fn(df, titulo=titulo)
    except TypeError:
        return fn(df)


def _fmt_op_cert(val) -> str:
    if val in (1, "1", True, "Sí", "Si"):
        return "Sí"
    return "No"


def _libro_op_activa() -> str:
    op = (request.args.get("op") or request.form.get("op") or "ingreso").strip().lower()
    if op not in {k for k, _ in LIBRO_OPS}:
        op = "ingreso"
    return op


def _pop_alertas() -> dict:
    out: dict = {}
    if "espino_lc_rebaje_ok" in session:
        out["rebaje_bodega_ok"] = session.pop("espino_lc_rebaje_ok")
    return out


def _opciones_maquinaria(
    conn,
    tipos,
    permitir_vacio: bool = False,
    valor_actual=None,
) -> list[tuple[str, str]]:
    from erp_maquinaria import _lista_select_maquinaria, etiqueta_maquinaria

    items = _lista_select_maquinaria(
        conn, tipos=tipos, valor_actual=valor_actual, solo_activos=True
    )
    opts = [(m["codigo"], etiqueta_maquinaria(m["codigo"], m["nombre"])) for m in items]
    if permitir_vacio:
        return [("", "— Sin tractor —")] + opts
    return opts


def _productos_stock_espino(demo, conn) -> list[dict]:
    stock_map = espino_bodega._stock_cc_map(conn)
    dfi = pd.read_sql_query(
        "SELECT id, producto, COALESCE(unidad_medida, ?) AS um FROM inventario ORDER BY producto",
        conn,
        params=(demo.DEFAULT_UNIDAD_INSUMO,),
    )
    out = []
    for _, r in dfi.iterrows():
        if not espino_bodega._es_producto_bodega_espino(str(r["producto"])):
            continue
        stock = stock_map.get(int(r["id"]), 0.0)
        if stock <= 0:
            continue
        out.append(
            {
                "producto": r["producto"],
                "stock_fmt": demo.f_cantidad(stock),
                "um": r["um"],
            }
        )
    return out


def _evento_meta_defaults(demo) -> dict:
    return {
        "fecha": hoy_demo(demo).isoformat(),
        "especie": "",
        "vol_agua": "",
        "aplicador": "",
        "op_cert": "",
        "maquinaria": "",
        "tractor": "",
    }


def _guardar_evento_meta(demo, src=None) -> dict:
    """Guarda cabecera del evento en sesión (sobrevive a agregar producto / cambio de prod)."""
    src = src if src is not None else request.values
    meta = session.get(META_KEY) or _evento_meta_defaults(demo)
    for key in ("fecha", "especie", "vol_agua", "aplicador", "maquinaria", "tractor"):
        if key not in src:
            continue
        val = (src.get(key) or "").strip()
        if val:
            meta[key] = val
    if "op_cert" in src:
        meta["op_cert"] = "1" if src.get("op_cert") in ("1", "on", "true", "True") else ""
    session[META_KEY] = meta
    return meta


def _leer_evento_meta(demo) -> dict:
    base = _evento_meta_defaults(demo)
    meta = session.get(META_KEY) or {}
    out = {**base, **{k: meta.get(k, base.get(k)) for k in base}}
    if not out.get("especie") and _especies_libro_campo(demo):
        out["especie"] = _especies_libro_campo(demo)[0]
    return out


def _siguiente_n_aplicacion(conn) -> int:
    """Correlativo propio El Espino (no hereda n° del Libro de Campo global)."""
    res = conn.execute(
        "SELECT MAX(CAST(n_aplicacion AS INTEGER)) FROM libro_campo "
        "WHERE UPPER(sector)=? AND n_aplicacion GLOB '[0-9]*' "
        "AND CAST(n_aplicacion AS INTEGER) < ?",
        (CC_ESPINO.upper(), _N_APP_HIST_MIN),
    ).fetchone()[0]
    return int(res) + 1 if res is not None else 1


def _siguiente_n_orden(conn) -> str:
    res = conn.execute(
        "SELECT MAX(CAST(n_orden AS INTEGER)) FROM libro_campo "
        "WHERE UPPER(sector)=? AND n_orden GLOB '[0-9]*'",
        (CC_ESPINO.upper(),),
    ).fetchone()[0]
    return str(int(res) + 1 if res is not None else 1)


def _ingreso(demo, conn) -> dict:
    siguiente = _siguiente_n_aplicacion(conn)
    car = session.get(CAR_KEY, [])
    _guardar_evento_meta(demo, request.values)
    meta = _leer_evento_meta(demo)

    from erp_maquinaria import TIPOS_MAQUINARIA_APLICACION, TIPOS_MAQUINARIA_TRACTOR

    productos = _productos_stock_espino(demo, conn)
    prod_sel = request.args.get("prod") or (productos[0]["producto"] if productos else "")
    phi_def = demo.dias_carencia_producto(conn, prod_sel, 0) if prod_sel else 0
    ing_def = demo._ingrediente_pppl_producto(conn, prod_sel) if prod_sel else ""
    stock_info = next((p for p in productos if p["producto"] == prod_sel), None)

    car_rows = []
    for item in car:
        car_rows.append(
            {
                "producto": item["producto"],
                "lote": item.get("lote_producto", ""),
                "ingrediente": item.get("ingrediente", ""),
                "dosis": demo.f_dosis_lc(item.get("dosis", 0)),
                "unidad_dosis": item.get("unidad_dosis", ""),
                "gasto_total": demo.f_cantidad(item.get("gasto_total", 0)),
                "um_gasto": item.get("um_gasto", ""),
                "dias_car": item.get("dias_car", 0),
            }
        )

    return {
        "siguiente_app": siguiente,
        "hoy": meta.get("fecha") or hoy_demo(demo).isoformat(),
        "form_fecha": meta.get("fecha") or hoy_demo(demo).isoformat(),
        "form_especie": meta.get("especie") or "",
        "form_vol_agua": meta.get("vol_agua") or "",
        "form_aplicador": meta.get("aplicador") or "",
        "form_op_cert": bool(meta.get("op_cert")),
        "form_maquinaria": meta.get("maquinaria") or "",
        "form_tractor": meta.get("tractor") or "",
        "especies": _especies_libro_campo(demo),
        "productos_stock": productos,
        "prod_sel": prod_sel,
        "stock_info": stock_info,
        "ing_def": ing_def,
        "phi_def": phi_def,
        "pppl_ok": demo.producto_pppl_aprobado(conn, prod_sel) if prod_sel else False,
        "unidades_dosis": UNIDADES_DOSIS,
        "maquinaria_opts": _opciones_maquinaria(
            conn, TIPOS_MAQUINARIA_APLICACION, valor_actual=meta.get("maquinaria")
        ),
        "tractor_opts": _opciones_maquinaria(
            conn,
            TIPOS_MAQUINARIA_TRACTOR,
            permitir_vacio=True,
            valor_actual=meta.get("tractor"),
        ),
        "lc_car": car_rows,
    }


def _historial(demo, conn) -> dict:
    from erp_maquinaria import enriquecer_columna_maquinaria

    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=180))
    ff = parse_date(request.args.get("hasta"), hoy)
    q_prod = (request.args.get("q") or "").strip()
    q_app = (request.args.get("n_app") or "").strip()

    filtros = ["fecha BETWEEN ? AND ?", "UPPER(sector)=?"]
    params: list = [str(fi), str(ff), CC_ESPINO.upper()]
    if q_prod:
        filtros.append(
            "(UPPER(COALESCE(producto,'')) LIKE ? OR UPPER(COALESCE(ingrediente,'')) LIKE ?)"
        )
        like = f"%{q_prod.upper()}%"
        params.extend([like, like])
    if q_app.isdigit():
        filtros.append("n_aplicacion = ?")
        params.append(int(q_app))
    else:
        filtros.append("CAST(n_aplicacion AS INTEGER) < ?")
        params.append(_N_APP_HIST_MIN)

    where_sql = " AND ".join(filtros)
    query = f"""SELECT n_aplicacion, fecha, sector, especie, producto, lote_producto, ingrediente,
                       dosis, unidad_dosis, vol_total, gasto_total, aplicadores,
                       operador_certificado, maquina, tractor, fecha_viable
                FROM libro_campo WHERE {where_sql}
                ORDER BY CAST(n_aplicacion AS INTEGER) DESC, id ASC"""
    df = pd.read_sql_query(query, conn, params=params)
    pdf_url = None
    pdf_filename = PDF_FILENAME
    if df.empty:
        return {
            "historial_grupos": [],
            "historial_stats": {"eventos": 0, "productos": 0},
            "filtro_desde": fi.isoformat(),
            "filtro_hasta": ff.isoformat(),
            "filtro_q": q_prod,
            "filtro_n_app": q_app,
            "pdf_historial_url": pdf_url,
            "pdf_historial_filename": pdf_filename,
        }

    df = df.rename(
        columns={
            "n_aplicacion": "N° APP",
            "fecha": "FECHA",
            "sector": "CUARTEL",
            "especie": "ESPECIE",
            "producto": "PRODUCTO",
            "lote_producto": "LOTE",
            "ingrediente": "ING ACTIVO",
            "dosis": "DOSIS 100L",
            "unidad_dosis": "UNIDAD",
            "vol_total": "VOL AGUA LT",
            "gasto_total": "TOTAL PROD",
            "aplicadores": "APLICADOR",
            "operador_certificado": "OP. CERT.",
            "maquina": "MAQUINARIA",
            "tractor": "TRACTOR",
            "fecha_viable": "FECHA VIABLE PHI",
        }
    )
    df = enriquecer_columna_maquinaria(conn, df, "MAQUINARIA")
    df = enriquecer_columna_maquinaria(conn, df, "TRACTOR")
    if "OP. CERT." in df.columns:
        df["OP. CERT."] = df["OP. CERT."].apply(_fmt_op_cert)

    blob = _generar_pdf_historial(demo, df)
    if blob:
        pdf_url = pdf_download_url(store_pdf(blob, PDF_FILENAME), PDF_FILENAME)

    col_app = "N° APP"
    grupos = []
    for n_app, grp in df.groupby(col_app, sort=False):
        grp = grp.reset_index(drop=True)
        base = grp.iloc[0]
        productos = []
        for _, row in grp.iterrows():
            ing = str(row.get("ING ACTIVO", "") or "").strip()
            if not ing:
                try:
                    from erp_inventario_ia import resolver_ingrediente_activo

                    ing = resolver_ingrediente_activo(conn, row["PRODUCTO"]) or ""
                except Exception:
                    ing = ""
            productos.append(
                {
                    "producto": row["PRODUCTO"],
                    "lote": row.get("LOTE", ""),
                    "ing_activo": ing,
                    "dosis": demo.f_dosis_lc(row.get("DOSIS 100L", 0)),
                    "unidad": row.get("UNIDAD", ""),
                    "total": demo.f_cantidad(row.get("TOTAL PROD", 0)),
                    "phi": str(row.get("FECHA VIABLE PHI", ""))[:10],
                }
            )
        grupos.append(
            {
                "num": int(n_app),
                "fecha": str(base.get("FECHA", ""))[:10],
                "cuartel": base.get("CUARTEL", CC_ESPINO),
                "especie": base.get("ESPECIE", ""),
                "vol_agua": demo.f_decimal(base.get("VOL AGUA LT", 0)),
                "maquinaria": base.get("MAQUINARIA", ""),
                "tractor": base.get("TRACTOR", ""),
                "aplicador": base.get("APLICADOR", ""),
                "op_cert": base.get("OP. CERT.", "No"),
                "productos": productos,
            }
        )

    return {
        "historial_grupos": grupos,
        "historial_stats": {"eventos": df[col_app].nunique(), "productos": len(df)},
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "filtro_q": q_prod,
        "filtro_n_app": q_app,
        "pdf_historial_url": pdf_url,
        "pdf_historial_filename": pdf_filename,
    }


def _desfase(demo, conn) -> dict:
    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)
    try:
        dias_v = int(request.args.get("ventana", "14"))
    except ValueError:
        dias_v = 14
    dias_v = max(1, min(60, dias_v))

    df_lc_sin, df_bod_sin = demo._calcular_desfaces_lc_bodega(conn, fi, ff, dias_v)
    cc_u = CC_ESPINO.upper()
    if not df_lc_sin.empty and "CUARTEL" in df_lc_sin.columns:
        df_lc_sin = df_lc_sin[df_lc_sin["CUARTEL"].astype(str).str.upper() == cc_u]
    if not df_bod_sin.empty and "CUARTEL" in df_bod_sin.columns:
        df_bod_sin = df_bod_sin[df_bod_sin["CUARTEL"].astype(str).str.upper() == cc_u]

    lc_rows = df_lc_sin.fillna("").to_dict(orient="records") if not df_lc_sin.empty else []
    bod_rows = df_bod_sin.fillna("").to_dict(orient="records") if not df_bod_sin.empty else []

    return {
        "desfase_lc_rows": lc_rows,
        "desfase_bod_rows": bod_rows,
        "desfase_ok": len(lc_rows) == 0 and len(bod_rows) == 0,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "ventana_dias": dias_v,
    }


def post_agregar_producto(demo, conn) -> dict:
    _guardar_evento_meta(demo, request.form)
    prod = (request.form.get("producto") or "").strip()
    if not prod:
        return {"ok": False, "msg": "Seleccione un producto con stock en bodega El Espino."}
    if not demo.producto_pppl_aprobado(conn, prod):
        return {"ok": False, "msg": "Producto no autorizado en PPPL."}
    try:
        dos_base = float(request.form.get("dosis") or 0)
        total_prod = float(request.form.get("gasto_total") or 0)
        dias_car = int(request.form.get("dias_car") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Valores numéricos inválidos."}

    from erp_inventario_ia import resolver_ingrediente_activo

    um_prod = demo._um_producto_inventario(conn, prod)
    car = session.get(CAR_KEY, [])
    car.append(
        {
            "producto": prod,
            "lote_producto": (request.form.get("lote") or "").strip(),
            "ingrediente": resolver_ingrediente_activo(conn, prod)
            or (request.form.get("ingrediente") or "").strip(),
            "dosis": dos_base,
            "unidad_dosis": request.form.get("unidad_dosis") or UNIDADES_DOSIS[0],
            "gasto_total": total_prod,
            "um_gasto": um_prod,
            "dias_car": dias_car,
        }
    )
    session[CAR_KEY] = car
    return {"ok": True, "msg": f"Producto {prod} agregado al evento.", "extra": {"op": "ingreso"}}


def post_guardar_evento(demo, conn) -> dict:
    car = session.get(CAR_KEY, [])
    if not car:
        return {"ok": False, "msg": "Agregue al menos un producto al evento."}
    maquinaria = (request.form.get("maquinaria") or "").strip()
    aplicador = (request.form.get("aplicador") or "").strip()
    try:
        total_agua = float(request.form.get("vol_agua") or 0)
    except (TypeError, ValueError):
        total_agua = 0
    if not maquinaria:
        return {"ok": False, "msg": "Seleccione la maquinaria / nebulizador."}
    if not aplicador:
        return {"ok": False, "msg": "Ingrese el nombre del aplicador."}
    if total_agua <= 0:
        return {"ok": False, "msg": "Ingrese el volumen total de agua aplicada."}

    fe_app = parse_date(request.form.get("fecha"), hoy_demo(demo))
    especies = _especies_libro_campo(demo)
    especie = request.form.get("especie") or (especies[0] if especies else "Cerezos")
    op_cert = request.form.get("op_cert") == "1"
    tractor = (request.form.get("tractor") or "").strip()

    for item in car:
        ok, msg, _, _, _ = espino_bodega.validar_salida_bodega(
            demo,
            conn,
            float(item.get("gasto_total") or 0),
            producto=str(item.get("producto") or ""),
        )
        if not ok:
            return {"ok": False, "msg": msg}

    n_app = _siguiente_n_aplicacion(conn)
    n_orden = _siguiente_n_orden(conn)

    for item in car:
        demo._insertar_linea_libro_campo(
            conn,
            fe_app,
            n_app,
            CC_ESPINO,
            especie,
            item,
            total_agua,
            aplicador,
            op_cert,
            maquinaria,
            tractor,
            n_orden=n_orden,
        )

    for item in car:
        ok, msg = espino_bodega.registrar_salida_bodega(
            demo,
            conn,
            float(item.get("gasto_total") or 0),
            producto=str(item.get("producto") or ""),
            fecha=fe_app,
        )
        if not ok:
            return {"ok": False, "msg": msg}
    conn.commit()
    prods_txt = ", ".join(i["producto"] for i in car)
    demo.registrar_accion("LIBRO CAMPO ESPINO", f"App N°{n_app} · {CC_ESPINO} · {prods_txt}")
    session[CAR_KEY] = []
    session.pop(META_KEY, None)
    rebajes = [
        f"{p['producto']} −{demo.f_cantidad(p.get('gasto_total', 0))} {p.get('um_gasto', '')}"
        for p in car
    ]
    session["espino_lc_rebaje_ok"] = {"n_app": n_app, "rebajes": rebajes}
    return {
        "ok": True,
        "msg": f"Aplicación N° {n_app:05d} guardada. Bodega rebajada automáticamente.",
        "extra": {"op": "ingreso", "sec": "libro_campo"},
    }


def post_pop_producto(demo) -> None:
    _guardar_evento_meta(demo, request.form)
    car = session.get(CAR_KEY, [])
    if car:
        car.pop()
        session[CAR_KEY] = car


def gather_libro_campo(demo, conn, op_override: str | None = None) -> dict:
    _ensure_maquinaria_tenant(conn)
    op = op_override or _libro_op_activa()
    ctx = {
        "libro_ops": LIBRO_OPS,
        "lc_op_activa": op,
        "cc_espino": CC_ESPINO,
        **_pop_alertas(),
    }
    if op == "ingreso":
        ctx.update(_ingreso(demo, conn))
    elif op == "historial":
        ctx.update(_historial(demo, conn))
    elif op == "desfase":
        ctx.update(_desfase(demo, conn))
    return ctx
