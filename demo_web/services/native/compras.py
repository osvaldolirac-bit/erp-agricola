from __future__ import annotations

import pandas as pd
from flask import flash, render_template, request, session, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("historial", "HISTORIAL"),
    ("ingreso", "INGRESO"),
    ("caja", "CAJA CHICA"),
]

MODOS_INGRESO = [
    ("gastos", "Gastos varios"),
    ("agro", "Insumos bodega"),
    ("pet", "Petróleo"),
]

SQL_ETIQUETA_TIPO = """
    CASE
        WHEN tipo IN ('Gasto Operacional', 'Gasto Vario') THEN 'Gasto Operacional'
        WHEN tipo IN ('Gasto Operacional Petróleo', 'Gasto Vario Petróleo') THEN 'Gasto Operacional Petróleo'
        WHEN TRIM(COALESCE(concepto, '')) LIKE '[%' THEN 'Insumos'
        ELSE COALESCE(NULLIF(TRIM(tipo), ''), 'Factura')
    END
"""

_CAR_KEY = "compras_car"


def _get_car() -> list[dict]:
    return list(session.get(_CAR_KEY) or [])


def _set_car(car: list[dict]) -> None:
    session[_CAR_KEY] = car
    session.modified = True


def _clear_car() -> None:
    session.pop(_CAR_KEY, None)
    session.modified = True


def _folio_interno(conn, fecha) -> str:
    """N° documento automático cuando la compra se ingresa sin factura oficial (INT-…)."""
    prefijo = f"INT-{str(fecha).replace('-', '')}-"
    n = conn.execute(
        "SELECT COUNT(*) FROM facturas WHERE nro_documento LIKE ? AND nro_documento NOT LIKE '%_P'",
        (prefijo + "%",),
    ).fetchone()[0]
    return f"{prefijo}{int(n) + 1:02d}"


def _es_documento_interno(nro_documento: str | None) -> bool:
    """True si el N° doc es interno (sin factura real), p.ej. INT-20260810-01."""
    doc = (nro_documento or "").strip().upper()
    if not doc:
        return True
    return doc.startswith("INT-") or doc.startswith("INT/")


def _ensure_folio_interno_col(conn) -> None:
    from erp_solo_lectura import conn_en_solo_lectura

    cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
    if "folio_interno" not in cols:
        if conn_en_solo_lectura(conn):
            return
        conn.execute("ALTER TABLE facturas ADD COLUMN folio_interno TEXT DEFAULT ''")
        conn.commit()
    # El correlativo solo aplica a facturas reales: limpiar en documentos INT-…
    if not conn_en_solo_lectura(conn):
        conn.execute(
            """
            UPDATE facturas
            SET folio_interno=''
            WHERE TRIM(COALESCE(folio_interno, '')) != ''
              AND (
                UPPER(TRIM(nro_documento)) LIKE 'INT-%'
                OR UPPER(TRIM(nro_documento)) LIKE 'INT/%'
              )
            """
        )
        conn.commit()


def _es_doc_interno(nro_documento: str) -> bool:
    doc = (nro_documento or "").strip().upper()
    if not doc:
        return True
    return doc.startswith("INT-") or doc.startswith("INT/")


def _es_factura_real_gasto_operacional(nro_documento: str, tipo: str | None) -> bool:
    """Solo facturas reales de gasto operacional (no INT-, no sueldos _RRHH)."""
    doc = (nro_documento or "").strip().upper()
    if not doc or doc.endswith("_P") or doc.endswith("_RRHH"):
        return False
    if _es_doc_interno(doc):
        return False
    t = (tipo or "").strip()
    return t in ("Gasto Operacional", "Gasto Vario")


def _ensure_imputar_bruto_col(conn) -> None:
    """Marca si la imputación CC debe respetarse como neto (iva_bruto desmarcado)."""
    from erp_solo_lectura import conn_en_solo_lectura

    cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
    if "imputar_bruto" not in cols:
        if conn_en_solo_lectura(conn):
            return
        conn.execute("ALTER TABLE facturas ADD COLUMN imputar_bruto INTEGER DEFAULT 1")
        conn.commit()
    if conn_en_solo_lectura(conn):
        return
    # Revertir marcas erróneas (sueldos, INT-, otros tipos)
    conn.execute(
        """
        UPDATE facturas
        SET imputar_bruto = 1
        WHERE COALESCE(imputar_bruto, 1) = 0
          AND (
            nro_documento LIKE '%_RRHH'
            OR UPPER(TRIM(nro_documento)) LIKE 'INT-%'
            OR UPPER(TRIM(nro_documento)) LIKE 'INT/%'
            OR COALESCE(tipo, '') NOT IN ('Gasto Operacional', 'Gasto Vario')
          )
        """
    )
    # Solo facturas reales de gasto operacional donde _P ya suma neto (~bruto/1.19)
    conn.execute(
        """
        UPDATE facturas
        SET imputar_bruto = 0
        WHERE nro_documento NOT LIKE '%_P'
          AND nro_documento NOT LIKE '%_RRHH'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT-%'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT/%'
          AND COALESCE(tipo, '') IN ('Gasto Operacional', 'Gasto Vario')
          AND monto_total > 0
          AND id IN (
            SELECT par.id
            FROM facturas par
            INNER JOIN facturas p
              ON p.nro_documento = par.nro_documento || '_P'
             AND p.proveedor = par.proveedor
            WHERE par.nro_documento NOT LIKE '%_P'
              AND par.nro_documento NOT LIKE '%_RRHH'
              AND UPPER(TRIM(par.nro_documento)) NOT LIKE 'INT-%'
              AND UPPER(TRIM(par.nro_documento)) NOT LIKE 'INT/%'
              AND COALESCE(par.tipo, '') IN ('Gasto Operacional', 'Gasto Vario')
            GROUP BY par.id, par.monto_total
            HAVING ABS(SUM(COALESCE(p.monto_imputado, 0)) * 1.19 - par.monto_total)
                   < MAX(0.02, par.monto_total * 0.005)
               AND SUM(COALESCE(p.monto_imputado, 0)) > 0.01
          )
        """
    )
    conn.commit()


def _siguiente_correlativo_interno(conn, razon_social: str | None = None) -> str:
    """Siguiente correlativo por razón social (solo facturas reales, no INT-)."""
    sql = """
        SELECT MAX(CAST(folio_interno AS INTEGER))
        FROM facturas
        WHERE TRIM(COALESCE(folio_interno, '')) != ''
          AND folio_interno GLOB '[0-9]*'
          AND nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT-%'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT/%'
    """
    params: list = []
    if razon_social:
        sql += " AND TRIM(COALESCE(razon_social, '')) = ?"
        params.append(str(razon_social).strip())
    row = conn.execute(sql, params).fetchone()
    return str(int(row[0] or 0) + 1)


def _correlativo_duplicado(conn, folio: str, razon_social: str, exclude_id: int = 0):
    """True si el correlativo ya existe en la misma razón social (puede repetirse entre razones)."""
    return conn.execute(
        """
        SELECT id FROM facturas
        WHERE TRIM(COALESCE(folio_interno,''))=?
          AND TRIM(COALESCE(razon_social,''))=?
          AND id!=?
          AND nro_documento NOT LIKE '%_P'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT-%'
          AND UPPER(TRIM(nro_documento)) NOT LIKE 'INT/%'
        """,
        (folio, (razon_social or "").strip(), exclude_id),
    ).fetchone()


def _proveedores_options(conn) -> list[dict]:
    from erp_proveedores import etiqueta_proveedor, listar_proveedores

    return [
        {"nombre": p["nombre"], "label": etiqueta_proveedor(p["codigo"], p["nombre"])}
        for p in listar_proveedores(conn, solo_activos=True)
    ]


def _historial(demo, conn) -> dict:
    _ensure_folio_interno_col(conn)
    hoy = hoy_demo(demo)
    fi_def = demo._fecha_minima_facturas_compras(conn)
    row_fc = conn.execute(
        "SELECT MAX(fecha_compra) FROM facturas WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'"
    ).fetchone()
    fmax_db = pd.to_datetime(row_fc[0]).date() if row_fc and row_fc[0] else hoy
    fi = parse_date(request.args.get("desde"), fi_def)
    ff = parse_date(request.args.get("hasta"), max(hoy, fmax_db))
    q = (request.args.get("q") or "").strip()

    sql = f"""
        SELECT id, nro_documento, COALESCE(folio_interno, '') AS folio_interno, proveedor,
               IFNULL(razon_social, 'ERP Demo Agrícola') AS razon_social,
               fecha_compra, fecha_vencimiento, {SQL_ETIQUETA_TIPO} AS tipo,
               COALESCE(NULLIF(TRIM(tipo_gasto), ''), ?) AS tipo_gasto_cc,
               concepto, monto_total
        FROM facturas
        WHERE monto_total > 0 AND nro_documento NOT LIKE '%_P'
          AND fecha_compra BETWEEN ? AND ?
    """
    params: list = [demo.TIPO_GASTO_SIN_CLASIFICAR, str(fi), str(ff)]
    if q:
        sql += (
            " AND (nro_documento LIKE ? OR COALESCE(folio_interno,'') LIKE ? OR proveedor LIKE ? "
            "OR concepto LIKE ? OR IFNULL(razon_social,'') LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    sql += " ORDER BY id DESC"
    df = pd.read_sql_query(sql, conn, params=params)

    siguientes_por_razon: dict[str, str] = {}
    rows = []
    for _, r in df.iterrows():
        nro = str(r["nro_documento"] or "").strip()
        es_interno = _es_documento_interno(nro)
        folio = "" if es_interno else (r["folio_interno"] or "").strip()
        razon = str(r["razon_social"] or "").strip()
        if razon not in siguientes_por_razon:
            siguientes_por_razon[razon] = _siguiente_correlativo_interno(conn, razon)
        rows.append(
            {
                "id": int(r["id"]),
                "nro_documento": nro,
                "folio_interno": folio,
                "es_doc_interno": es_interno,
                "puede_correlativo": (not es_interno),
                "siguiente_correlativo": siguientes_por_razon.get(razon, ""),
                "proveedor": r["proveedor"],
                "razon_social": r["razon_social"],
                "fecha_compra": str(r["fecha_compra"])[:10],
                "fecha_vencimiento": str(r["fecha_vencimiento"] or r["fecha_compra"])[:10],
                "tipo": r["tipo"],
                "tipo_gasto_cc": r["tipo_gasto_cc"],
                "concepto": (r["concepto"] or "")[:120],
                "concepto_full": r["concepto"] or "",
                "monto_total": demo.f_peso(r["monto_total"]),
                "monto_raw": float(r["monto_total"] or 0),
            }
        )
    pdf_url = None
    if not df.empty:
        df_pdf = df.rename(
            columns={
                "folio_interno": "CORRELATIVO",
                "nro_documento": "N° DOCUMENTO",
                "proveedor": "PROVEEDOR",
                "razon_social": "RAZÓN SOCIAL",
                "fecha_compra": "FECHA COMPRA",
                "tipo": "TIPO",
                "tipo_gasto_cc": "TIPO GASTO CC",
                "concepto": "DETALLE / CONCEPTO",
                "monto_total": "MONTO BRUTO",
            }
        ).copy()
        cols_pdf = [
            "CORRELATIVO",
            "N° DOCUMENTO",
            "PROVEEDOR",
            "RAZÓN SOCIAL",
            "FECHA COMPRA",
            "TIPO",
            "TIPO GASTO CC",
            "DETALLE / CONCEPTO",
            "MONTO BRUTO",
        ]
        cols_pdf = [c for c in cols_pdf if c in df_pdf.columns]
        blob = demo.generar_pdf_blob(
            df_pdf[cols_pdf],
            "HISTORIAL CONSOLIDADO DE COMPRAS",
            campo_suma_forzado="MONTO BRUTO",
        )
        if blob:
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, "historial_compras.pdf"))

    es_admin = bool(demo.es_admin()) and not bool(demo.es_solo_lectura())
    factura_edit = None
    factura_opts = []
    if es_admin and rows:
        factura_opts = [
            {
                "id": r["id"],
                "label": f"ID {r['id']} · {r['nro_documento']} · {r['proveedor']} · {r['monto_total']}",
            }
            for r in rows
        ]
        try:
            edit_id = int(request.args.get("factura_id") or rows[0]["id"])
        except ValueError:
            edit_id = rows[0]["id"]
        if edit_id not in {r["id"] for r in rows}:
            edit_id = rows[0]["id"]
        factura_edit = next(r for r in rows if r["id"] == edit_id)
        # normalizar tipo gasto para select
        tg = factura_edit["tipo_gasto_cc"]
        if tg == "Contratistas":
            tg = "Contratistas externos"
        tipos = list(getattr(demo, "TIPOS_GASTO_HISTORIAL_COMPRAS", []) or [])
        sistema = set(getattr(demo, "TIPOS_GASTO_SISTEMA", set()) or set())
        if tg in sistema:
            tg = getattr(demo, "TIPO_GASTO_SIN_CLASIFICAR", "Sin clasificar")
        if tg not in tipos and tipos:
            tg = tipos[0]
        factura_edit = dict(factura_edit)
        factura_edit["tipo_gasto_sel"] = tg

    razones = list(getattr(demo, "RAZONES_SOCIALES_COMPRAS", []) or [])
    tipos_gasto = list(getattr(demo, "TIPOS_GASTO_HISTORIAL_COMPRAS", []) or [])
    proveedores = _proveedores_options(conn) if es_admin else []

    puede_folio = not bool(demo.es_solo_lectura())
    if puede_folio and factura_edit:
        siguiente_corr = factura_edit.get("siguiente_correlativo") or _siguiente_correlativo_interno(
            conn, factura_edit.get("razon_social")
        )
    elif puede_folio:
        siguiente_corr = _siguiente_correlativo_interno(conn)
    else:
        siguiente_corr = ""

    return {
        "historial_rows": rows,
        "filtro_q": q,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "siguiente_correlativo": siguiente_corr,
        "n_registros": len(rows),
        "pdf_historial_url": pdf_url,
        "es_admin": es_admin,
        "puede_folio": puede_folio,
        "factura_edit": factura_edit,
        "factura_opts": factura_opts,
        "razones_sociales": razones,
        "tipos_gasto_historial": tipos_gasto,
        "proveedores_hist": proveedores,
    }


def _gather_ingreso(demo, conn) -> dict:
    modo = request.args.get("modo", "gastos")
    if modo not in {k for k, _ in MODOS_INGRESO}:
        modo = "gastos"

    dfi = pd.read_sql_query(
        "SELECT id, producto, familia, COALESCE(unidad_medida, 'kg') AS unidad_medida "
        "FROM inventario ORDER BY producto",
        conn,
    )
    productos = [
        {
            "id": int(r["id"]),
            "label": f"{r['producto']} ({r['unidad_medida']})",
            "producto": r["producto"],
            "um": r["unidad_medida"],
        }
        for _, r in dfi.iterrows()
    ]
    car = _get_car()
    car_rows = [
        {
            "producto": i["n"],
            "cantidad": i["c"],
            "um": i.get("um", demo.DEFAULT_UNIDAD_INSUMO),
            "neto": demo.f_peso(i["p"]),
            "total": demo.f_peso(i["t"]),
        }
        for i in car
    ]
    car_total = sum(i["t"] for i in car)
    proveedores = _proveedores_options(conn)
    return {
        "modo_ingreso": modo,
        "modos_ingreso": MODOS_INGRESO,
        "proveedores": proveedores,
        "sin_proveedores": not proveedores,
        "productos": productos,
        "familias": demo.listar_familias_producto(conn),
        "unidades": demo.UNIDADES_MEDIDA_INSUMO,
        "razones_sociales": demo.RAZONES_SOCIALES_COMPRAS,
        "tipos_gasto": demo.TIPOS_GASTO_ALTA,
        "centros_costo": demo.CENTROS_COSTO,
        "car_rows": car_rows,
        "car_total_bruto": demo.f_peso(car_total * 1.19) if car else "",
        "car_count": len(car),
        "hoy": hoy_demo(demo).isoformat(),
    }


def _caja_chica(demo, conn, user_email: str) -> dict:
    from erp_caja_chica import (
        _fechas_rango_movimientos,
        _slug_archivo,
        _titulo_pdf_caja_chica,
        dataframe_libro_mayor,
        listar_encargados,
        migrar_caja_chica,
    )

    migrar_caja_chica(conn)
    enc = listar_encargados(conn, solo_activos=True)
    if enc.empty:
        return {"caja_vacia": True, "caja_rows": [], "saldo_cierre": demo.f_peso(0)}

    opciones = {"": "Todos los encargados"}
    enc_list = []
    for _, r in enc.iterrows():
        eid = str(int(r["id"]))
        opciones[eid] = r["nombre"]
        enc_list.append({"id": int(r["id"]), "nombre": r["nombre"]})

    enc_raw = request.args.get("encargado", "")
    enc_id = int(enc_raw) if enc_raw.isdigit() else None
    fmin, fmax = _fechas_rango_movimientos(conn, enc_id, hoy=hoy_demo(demo))
    fi = parse_date(request.args.get("desde"), fmin)
    ff = parse_date(request.args.get("hasta"), max(fmax, fi))
    q = (request.args.get("q") or "").strip()

    df_lm, _ = dataframe_libro_mayor(
        conn, enc_id, fecha_desde=fi, fecha_hasta=ff, q_buscar=q,
    )
    saldo = float(df_lm["SALDO"].iloc[-1]) if not df_lm.empty else 0.0
    rows = []
    for _, r in df_lm.iterrows():
        rows.append(
            {
                "fecha": r["FECHA"],
                "encargado": r.get("ENCARGADO", ""),
                "documento": r["DOCUMENTO"],
                "proveedor": r["PROVEEDOR"],
                "debe": demo.f_peso(r["DEBE"]) if r["DEBE"] else "",
                "haber": demo.f_peso(r["HABER"]) if r["HABER"] else "",
                "saldo": demo.f_peso(r["SALDO"]),
            }
        )

    pdf_encargados = []
    ids_pdf = [enc_id] if enc_id else [e["id"] for e in enc_list]
    for eid in ids_pdf:
        nom = next((e["nombre"] for e in enc_list if e["id"] == eid), "Encargado")
        df_pdf, _ = dataframe_libro_mayor(
            conn, eid, fecha_desde=fi, fecha_hasta=ff, q_buscar=q,
        )
        if df_pdf.empty:
            continue
        df_pdf = df_pdf.drop(columns=["ENCARGADO"], errors="ignore")
        titulo = _titulo_pdf_caja_chica(nom, fi, ff)
        blob = demo.generar_pdf_blob(df_pdf, titulo, incluir_precios=False)
        if not blob:
            continue
        slug = _slug_archivo(nom)
        pdf_encargados.append(
            {
                "id": eid,
                "nombre": nom,
                "url": url_for(
                    "modules.pdf_download",
                    token=store_pdf(blob, f"caja_chica_{slug}.pdf"),
                ),
                "rows": len(df_pdf),
            }
        )

    return {
        "caja_vacia": False,
        "encargados": opciones,
        "encargados_list": enc_list,
        "encargado_sel": enc_raw,
        "caja_rows": rows,
        "caja_pdf_encargados": pdf_encargados,
        "saldo_cierre": demo.f_peso(saldo),
        "filtro_q": q,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "show_encargado_col": enc_id is None and rows and rows[0].get("encargado"),
        "hoy": hoy_demo(demo).isoformat(),
    }


def _post_add_car(demo) -> dict:
    modo_prod = request.form.get("modo_prod", "existente")
    try:
        cant = float(request.form.get("cantidad") or 0)
        neto = float(request.form.get("neto") or 0)
    except ValueError:
        return {"ok": False, "msg": "Cantidad o neto inválidos."}
    if cant <= 0 or neto <= 0:
        return {"ok": False, "msg": "Cantidad y neto deben ser mayores a cero."}

    car = _get_car()
    if modo_prod == "existente":
        pid_raw = request.form.get("producto_id") or ""
        if not pid_raw.isdigit():
            return {"ok": False, "msg": "Seleccione un insumo de bodega."}
        pid = int(pid_raw)
        row = None
        demo_mod = get_demo_module()
        conn = demo_mod.conectar_db()
        try:
            row = conn.execute(
                "SELECT producto, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
                (demo_mod.DEFAULT_UNIDAD_INSUMO, pid),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return {"ok": False, "msg": "Producto no encontrado."}
        car.append(
            {
                "id": pid,
                "n": row[0],
                "c": cant,
                "p": neto,
                "t": cant * neto,
                "nuevo": False,
                "um": row[1],
            }
        )
    else:
        nom = (request.form.get("prod_nuevo") or "").strip()
        if not nom:
            return {"ok": False, "msg": "Ingrese el nombre del producto nuevo."}
        car.append(
            {
                "id": None,
                "n": nom,
                "familia": request.form.get("familia") or "OTROS",
                "c": cant,
                "p": neto,
                "t": cant * neto,
                "nuevo": True,
                "um": request.form.get("um") or demo.DEFAULT_UNIDAD_INSUMO,
            }
        )
    _set_car(car)
    return {"ok": True, "msg": "Ítem agregado al carro."}


def _post_save_agro(demo, conn) -> dict:
    from erp_inventario_ia import poblar_ingredientes_inventario

    nro = (request.form.get("nro_doc") or "").strip()
    prov = (request.form.get("proveedor") or "").strip()
    fe = request.form.get("fecha_emision") or str(hoy_demo(demo))
    fv = request.form.get("fecha_vence") or str(hoy_demo(demo))
    car = _get_car()
    if not nro or not prov:
        return {"ok": False, "msg": "Proveedor y número de documento son obligatorios."}
    if not car:
        return {"ok": False, "msg": "Agregue al menos un ítem al carro."}

    desglose = [f"{i['c']} {i.get('um', demo.DEFAULT_UNIDAD_INSUMO)} x {i['n']}" for i in car]
    concepto = "[" + ", ".join(desglose) + "]"
    total_bruto = sum(i["t"] for i in car) * 1.19
    razon = request.form.get("razon_social") or demo.RAZONES_SOCIALES_COMPRAS[0]
    tipo_gasto = (request.form.get("tipo_gasto") or "Agroquímicos").strip() or "Agroquímicos"
    conn.execute(
        """INSERT INTO facturas
           (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, concepto, razon_social, tipo_gasto)
           VALUES (?,?,?,?,?,?,?,?)""",
        (nro, prov, fe, fv, total_bruto, concepto, razon, tipo_gasto),
    )
    for i in car:
        if i.get("nuevo") or i.get("id") is None:
            cur_ins = conn.execute(
                "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida) VALUES (?,?,?,?,?)",
                (i["n"], i.get("familia", "OTROS"), i["c"], i["p"], i.get("um", demo.DEFAULT_UNIDAD_INSUMO)),
            )
            poblar_ingredientes_inventario(conn, cur_ins.lastrowid)
        else:
            cur = conn.execute("SELECT stock, precio_medio FROM inventario WHERE id=?", (i["id"],)).fetchone()
            npmp = ((cur[0] * cur[1]) + (i["c"] * i["p"])) / (cur[0] + i["c"]) if (cur[0] + i["c"]) > 0 else i["p"]
            conn.execute(
                "UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?",
                (i["c"], npmp, i["id"]),
            )
    conn.commit()
    _clear_car()
    demo.registrar_accion("COMPRA", nro)
    return {"ok": True, "msg": f"Factura {nro} guardada. Stock y PMP actualizados."}


def _post_save_gastos(demo, conn) -> dict:
    prov = (request.form.get("proveedor") or "").strip()
    fe = request.form.get("fecha_emision") or str(hoy_demo(demo))
    fv = request.form.get("fecha_vence") or str(hoy_demo(demo))
    sin_doc = request.form.get("sin_doc") == "1"
    nro = (request.form.get("nro_doc") or "").strip()
    razon = request.form.get("razon_social") or demo.RAZONES_SOCIALES_COMPRAS[0]
    concepto = (request.form.get("concepto") or "").strip()
    tipo_gasto = request.form.get("tipo_gasto") or demo.TIPOS_GASTO_ALTA[0]
    iva_bruto = request.form.get("iva_bruto") == "1"
    try:
        mt = float(request.form.get("monto") or 0)
    except ValueError:
        return {"ok": False, "msg": "Monto inválido."}
    selcc = [c for c in demo.CENTROS_COSTO if request.form.get(f"cc_{c}") == "1"]

    if not prov:
        return {"ok": False, "msg": "El proveedor es obligatorio."}
    if not sin_doc and not nro:
        return {"ok": False, "msg": "Ingrese el número de documento."}
    if mt <= 0:
        return {"ok": False, "msg": "El monto debe ser mayor a cero."}
    if not selcc:
        return {"ok": False, "msg": "Seleccione al menos un centro de costo."}

    ng = _folio_interno(conn, fe) if sin_doc else nro
    imp = mt if iva_bruto else mt / 1.19
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total,
           monto_neto, tipo, concepto, razon_social, tipo_gasto, imputar_bruto)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ng,
            prov,
            fe,
            fv,
            mt,
            imp,
            "Gasto Operacional",
            concepto,
            razon,
            tipo_gasto,
            1 if iva_bruto else 0,
        ),
    )
    for c in selcc:
        conn.execute(
            """INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total,
               tipo, centro_costo, monto_imputado, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ng + "_P", prov, fe, fv, 0, "Gasto Operacional", c.upper(), imp / len(selcc), concepto, razon, tipo_gasto),
        )
    conn.commit()
    demo.registrar_accion("GASTO", ng)
    return {"ok": True, "msg": f"Gasto registrado bajo folio {ng}."}


def _post_save_petroleo(demo, conn) -> dict:
    prov = (request.form.get("proveedor") or "").strip()
    fe = request.form.get("fecha_emision") or str(hoy_demo(demo))
    fv = request.form.get("fecha_vence") or str(hoy_demo(demo))
    sin_doc = request.form.get("sin_doc") == "1"
    nro = (request.form.get("nro_doc") or "").strip()
    razon = request.form.get("razon_social") or demo.RAZONES_SOCIALES_COMPRAS[0]
    concepto = (request.form.get("concepto") or "").strip()
    try:
        litros = float(request.form.get("litros") or 0)
        mt = float(request.form.get("monto") or 0)
    except ValueError:
        return {"ok": False, "msg": "Litros o monto inválidos."}

    if not prov:
        return {"ok": False, "msg": "El proveedor es obligatorio."}
    if not sin_doc and not nro:
        return {"ok": False, "msg": "Ingrese el número de documento."}
    if mt <= 0:
        return {"ok": False, "msg": "El total debe ser mayor a cero."}
    if litros <= 0:
        return {"ok": False, "msg": "Ingrese los litros cargados al estanque."}

    ng = _folio_interno(conn, fe) if sin_doc else nro
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total,
           tipo, concepto, razon_social, tipo_gasto) VALUES (?,?,?,?,?,?,?,?,?)""",
        (ng, prov, fe, fv, mt, "Gasto Operacional Petróleo", concepto, razon, "Petróleo"),
    )
    conn.execute(
        "INSERT INTO petroleo (tipo, litros, proveedor, monto_total_compra, fecha) VALUES (?,?,?,?,?)",
        ("Carga", litros, prov, mt, fe),
    )
    demo._recalcular_imputacion_salidas_petroleo(conn)
    conn.commit()
    demo.registrar_accion("GASTO PETROLEO", ng)
    demo.registrar_accion("PETROLEO", f"Carga {litros}L — {ng}")
    return {"ok": True, "msg": f"Compra petróleo {ng}: {demo.f_decimal(litros)} L al estanque."}


def _post_caja_mov(demo, conn, user_email: str) -> dict:
    enc_id = int(request.form.get("encargado_id") or 0)
    fecha = request.form.get("fecha") or str(hoy_demo(demo))
    tipo = request.form.get("tipo_mov") or "egreso"
    documento = (request.form.get("documento") or "").strip()
    proveedor = (request.form.get("proveedor") or "").strip()
    try:
        monto = float(request.form.get("monto") or 0)
    except ValueError:
        return {"ok": False, "msg": "Monto inválido."}

    if not enc_id:
        return {"ok": False, "msg": "Seleccione encargado."}
    if not documento:
        return {"ok": False, "msg": "Ingrese el documento."}
    if tipo == "egreso" and not proveedor:
        return {"ok": False, "msg": "Ingrese el proveedor o detalle del egreso."}
    if monto <= 0:
        return {"ok": False, "msg": "El monto debe ser mayor a cero."}

    debe = monto if tipo == "egreso" else 0.0
    haber = monto if tipo == "ingreso" else 0.0
    detalle = proveedor if tipo == "egreso" else documento
    f_reg = demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO caja_chica_movimientos
           (encargado_id, fecha, detalle, documento, proveedor, debe, haber, usuario, fecha_registro)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            enc_id, fecha, detalle, documento, proveedor if tipo == "egreso" else "",
            debe, haber, user_email, f_reg,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT nombre FROM encargados_compras WHERE id=?", (enc_id,)).fetchone()
    nom = row[0] if row else str(enc_id)
    etiqueta = f"{documento} — {proveedor}" if tipo == "egreso" else documento
    demo.registrar_accion("CAJA CHICA", f"{nom}: {etiqueta} ${int(monto):,}")
    return {"ok": True, "msg": "Movimiento de caja chica registrado."}



def _post_asignar_folio_interno(demo, conn) -> dict:
    """Registra correlativo solo en documentos con N° de factura real (no INT-…)."""
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede asignar correlativo."}
    _ensure_folio_interno_col(conn)
    try:
        fid = int(request.form.get("factura_id") or 0)
    except ValueError:
        fid = 0
    fila = conn.execute(
        "SELECT id, nro_documento, COALESCE(folio_interno, ''), "
        "TRIM(COALESCE(razon_social, '')) "
        "FROM facturas WHERE id=? AND nro_documento NOT LIKE '%_P'",
        (fid,),
    ).fetchone()
    if not fila:
        return {"ok": False, "msg": "Documento no encontrado."}

    doc = str(fila[1] or "").strip()
    if _es_documento_interno(doc):
        return {
            "ok": False,
            "msg": "El correlativo solo aplica a documentos con N° de factura real (no internos INT-…).",
        }
    folio_old = str(fila[2] or "").strip()
    razon = str(fila[3] or "").strip()
    folio_new = (request.form.get("folio_interno") or "").strip()
    if not folio_new:
        return {"ok": False, "msg": "Ingrese el correlativo."}

    # Unicidad por razón social: el mismo número puede repetirse entre razones (mismo mes u otro).
    if _correlativo_duplicado(conn, folio_new, razon, fid):
        return {
            "ok": False,
            "msg": f"El correlativo {folio_new} ya está usado en otra factura de esta razón social.",
        }

    conn.execute("UPDATE facturas SET folio_interno=? WHERE id=?", (folio_new, fid))
    conn.commit()
    demo.registrar_accion(
        "COMPRA",
        f"Correlativo ID {fid} (factura {doc} · {razon or '—'}): {folio_old or '—'} → {folio_new}",
    )
    return {
        "ok": True,
        "msg": f"Correlativo registrado: {folio_new}.",
    }


def _post_corregir_factura(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede editar documentos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo administradores pueden editar documentos."}
    clave = (request.form.get("clave_maestra") or "").strip()
    if clave != getattr(demo, "CLAVE_MAESTRA", ""):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        fid = int(request.form.get("factura_id") or 0)
    except ValueError:
        fid = 0
    fila = conn.execute(
        "SELECT id, nro_documento, proveedor, fecha_compra, fecha_vencimiento, monto_total, "
        "concepto, tipo, razon_social, tipo_gasto, COALESCE(contratista_id, 0) "
        "FROM facturas WHERE id=? AND nro_documento NOT LIKE '%_P'",
        (fid,),
    ).fetchone()
    if not fila:
        return {"ok": False, "msg": "Documento no encontrado."}

    doc_old = str(fila[1] or "")
    prov_old = str(fila[2] or "")
    monto_old = float(fila[5] or 0)
    doc_new = (request.form.get("nro_documento") or "").strip()
    prov_new = (request.form.get("proveedor") or "").strip()
    nrazon = (request.form.get("razon_social") or "").strip()
    nconcepto = (request.form.get("concepto") or "").strip()
    nfe = (request.form.get("fecha_compra") or "").strip()
    nfv = (request.form.get("fecha_vencimiento") or nfe).strip()
    ntipo_gasto = (request.form.get("tipo_gasto") or "").strip()
    try:
        nmonto = float(request.form.get("monto_total") or 0)
    except ValueError:
        return {"ok": False, "msg": "Monto inválido."}
    if not doc_new or not prov_new:
        return {"ok": False, "msg": "Proveedor y N° documento son obligatorios."}
    if nmonto <= 0:
        return {"ok": False, "msg": "El monto bruto debe ser superior a $0."}

    razones = list(getattr(demo, "RAZONES_SOCIALES_COMPRAS", []) or [])
    if nrazon not in razones and razones:
        nrazon = razones[0]
    tg_guardar = demo.tipo_gasto_canonico_contratista(ntipo_gasto)
    if int(fila[10] or 0) != 0:
        tg_guardar = "Contratistas"

    _ensure_folio_interno_col(conn)
    folio_new = (request.form.get("folio_interno") or "").strip()
    # Correlativo solo si el N° documento es factura real; unicidad por razón social.
    if _es_documento_interno(doc_new):
        folio_new = ""
    elif folio_new and _correlativo_duplicado(conn, folio_new, nrazon, fid):
        return {
            "ok": False,
            "msg": f"El correlativo {folio_new} ya está usado en otra factura de esta razón social.",
        }
    conn.execute(
        "UPDATE facturas SET nro_documento=?, folio_interno=?, proveedor=?, fecha_compra=?, fecha_vencimiento=?, "
        "monto_total=?, concepto=?, razon_social=?, tipo_gasto=? WHERE id=?",
        (doc_new, folio_new, prov_new, nfe, nfv, nmonto, nconcepto, nrazon, tg_guardar, fid),
    )
    demo._actualizar_tipo_gasto_factura(conn, doc_new, prov_new, tg_guardar)
    n_imp = demo._sincronizar_imputaciones_p_factura(
        conn,
        doc_old,
        prov_old,
        doc_new,
        prov_new,
        monto_old,
        nmonto,
        nfe,
        nfv,
        nconcepto,
        nrazon,
        tg_guardar,
    )
    conn.commit()
    det = f"Corrección ID {fid} — {doc_new} — {nrazon}"
    if n_imp:
        det += f" | {n_imp} imputación(es) _P"
    demo.registrar_accion("COMPRA", det)
    msg = "Documento actualizado."
    if n_imp:
        msg += f" Se actualizaron {n_imp} imputación(es) en centros de costo."
    return {"ok": True, "msg": msg}


def _post_eliminar_factura(demo, conn) -> dict:
    if demo.es_solo_lectura():
        return {"ok": False, "msg": "Modo solo lectura: no puede eliminar documentos."}
    if not demo.es_admin():
        return {"ok": False, "msg": "Solo administradores pueden eliminar documentos."}
    clave = (request.form.get("clave_maestra") or "").strip()
    if clave != getattr(demo, "CLAVE_MAESTRA", ""):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        fid = int(request.form.get("factura_id") or 0)
    except ValueError:
        fid = 0
    fila = conn.execute(
        "SELECT id, nro_documento, proveedor FROM facturas WHERE id=? AND nro_documento NOT LIKE '%_P'",
        (fid,),
    ).fetchone()
    if not fila:
        return {"ok": False, "msg": "Documento no encontrado."}
    doc, prov = str(fila[1] or ""), str(fila[2] or "")
    conn.execute("DELETE FROM facturas WHERE id=?", (fid,))
    conn.execute(
        "DELETE FROM facturas WHERE nro_documento=? AND proveedor=?",
        (doc + "_P", prov),
    )
    conn.commit()
    demo.registrar_accion("BORRADO", doc)
    return {"ok": True, "msg": f"Documento {doc} eliminado."}


def gather_compras(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    sec = request.args.get("sec", "historial")
    if sec not in {k for k, _ in SECCIONES}:
        sec = "historial"

    conn = demo.conectar_db()
    try:
        demo._migrar_tipo_gasto_operacional(conn)
        _ensure_imputar_bruto_col(conn)
        ctx: dict = {"secciones": SECCIONES, "sec_activa": sec}
        if sec == "historial":
            ctx.update(_historial(demo, conn))
        elif sec == "ingreso":
            ctx.update(_gather_ingreso(demo, conn))
        elif sec == "caja":
            ctx.update(_caja_chica(demo, conn, user_email))
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    sec = request.args.get("sec", "historial")
    modo = request.args.get("modo") or request.form.get("modo", "gastos")

    if request.method == "POST":
        action = request.form.get("action", "")
        conn = demo.conectar_db()
        try:
            demo._migrar_tipo_gasto_operacional(conn)
            _ensure_imputar_bruto_col(conn)
            result: dict | None = None
            if action == "add_car":
                result = _post_add_car(demo)
            elif action == "undo_car":
                car = _get_car()
                if car:
                    car.pop()
                    _set_car(car)
                    result = {"ok": True, "msg": "Último ítem removido del carro."}
                else:
                    result = {"ok": False, "msg": "El carro está vacío."}
            elif action == "save_agro":
                result = _post_save_agro(demo, conn)
            elif action == "save_gastos":
                result = _post_save_gastos(demo, conn)
            elif action == "save_petroleo":
                result = _post_save_petroleo(demo, conn)
            elif action == "caja_mov":
                result = _post_caja_mov(demo, conn, user_email)
            elif action == "asignar_folio_interno":
                result = _post_asignar_folio_interno(demo, conn)
            elif action == "corregir_factura":
                result = _post_corregir_factura(demo, conn)
            elif action == "eliminar_factura":
                result = _post_eliminar_factura(demo, conn)

            if result:
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec}
                if sec == "ingreso":
                    extra["modo"] = modo
                if action == "caja_mov":
                    extra["encargado"] = request.form.get("encargado_id", "")
                if action in {"corregir_factura", "eliminar_factura", "asignar_folio_interno"}:
                    extra["sec"] = "historial"
                    for k in ("q", "desde", "hasta"):
                        v = (request.form.get(k) or "").strip()
                        if v:
                            extra[k] = v
                    if action == "corregir_factura" and result.get("ok"):
                        fid = (request.form.get("factura_id") or "").strip()
                        if fid:
                            extra["factura_id"] = fid
                return redirect_module("compras", **extra)
        finally:
            conn.close()

    ctx = gather_compras(user_email, user_rol)
    return render_template(
        "modules/compras.html",
        page_title="Compras",
        active_key="Compras",
        title="📦 Compras e historial",
        **ctx,
    )
