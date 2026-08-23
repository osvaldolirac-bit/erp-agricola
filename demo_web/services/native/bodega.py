from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, session, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date, parse_decimal_cl

SECCIONES = [
    ("stock", "📊 STOCK ACTUAL"),
    ("salida", "🔄 SALIDA"),
    ("pppl", "🌿 PPPL"),
    ("apertura", "📋 STOCK INICIAL"),
    ("consulta", "🔍 CONSULTA CUARTEL"),
    ("desfase", "⚠️ DESFASE LC"),
]

SECCIONES_CERT = [
    ("pppl", "🌿 PPPL"),
    ("stock", "📊 STOCK CONSULTA"),
]

_ESTADO_CSS = {
    "AUTORIZADO": "success",
    "PENDIENTE": "warning",
    "DESINCronizado": "warning",
    "SIN_REFERENCIA": "danger",
    "NO_REQUIERE": "secondary",
}


def _secciones(demo) -> list[tuple[str, str]]:
    return SECCIONES_CERT if demo.es_certificacion() else SECCIONES


def _check_master(demo, clave: str) -> bool:
    return (clave or "").strip() == demo.CLAVE_MAESTRA


def _redirect_bodega(sec: str, **extra) -> redirect_module:
    return redirect_module("bodega", sec=sec, **extra)


def _pop_alertas() -> dict:
    out = {}
    if "bodega_alerta_lc" in session:
        out["alerta_lc"] = session.pop("bodega_alerta_lc")
    return out


def _stock_rows(demo, dfs_view: pd.DataFrame, con_precio: bool) -> list[dict]:
    rows = []
    for _, r in dfs_view.iterrows():
        row = {
            "producto": r["producto"],
            "ing_activo": r.get("ingrediente_activo", ""),
            "familia": r.get("familia", ""),
            "stock": demo.f_cantidad(r["stock"]),
            "um": r.get("unidad_medida", "kg"),
            "pppl": "Sí" if r.get("pppl_aprobado") else "No",
            "phi": int(r.get("dias_carencia") or 0),
        }
        if con_precio:
            row["pmp"] = demo.f_peso(r.get("precio_medio") or 0)
        rows.append(row)
    return rows


def _stock(demo, conn, cert: bool = False) -> dict:
    dfs = pd.read_sql_query(
        """SELECT id, producto, familia, stock, COALESCE(unidad_medida, 'kg') AS unidad_medida,
                  precio_medio, pppl_aprobado, dias_carencia, COALESCE(ingrediente_activo,'') AS ingrediente_activo
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
    if not cert:
        dfs_op = dfs_view.drop(columns=["precio_medio", "id"], errors="ignore").rename(
            columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"},
        )
        if not dfs_op.empty and "pppl_aprobado" in dfs_op.columns:
            dfs_op = dfs_op.rename(columns={"pppl_aprobado": "PPPL"})
            dfs_op["PPPL"] = dfs_op["PPPL"].apply(lambda v: int(bool(v)))
        blob = None
        if not dfs_op.empty:
            blob = demo.generar_pdf_blob(
                dfs_op,
                "STOCK ACTUAL (SIN PRECIOS)",
                incluir_precios=False,
                estilo_celda_fn=demo._pdf_estilo_stock_pppl,
            )
        if blob:
            token = store_pdf(blob, "stock_operativo.pdf")
            pdf_url = url_for("modules.pdf_download", token=token)

    edit_id = request.args.get("edit_id")
    edit_item = None
    if not dfs_view.empty and demo.es_admin() and not cert:
        sel_id = None
        if edit_id and str(edit_id).isdigit():
            sel_id = int(edit_id)
        if sel_id is None:
            sel_id = int(dfs_view.iloc[0]["id"])
        match = dfs_view[dfs_view["id"] == sel_id]
        if not match.empty:
            r = match.iloc[0]
            edit_item = {
                "id": int(r["id"]),
                "producto": r["producto"],
                "familia": r["familia"] or "",
                "stock": float(r["stock"] or 0),
                "unidad_medida": r["unidad_medida"],
                "precio_medio": float(r["precio_medio"] or 0),
                "ingrediente_activo": r.get("ingrediente_activo") or demo._ingrediente_pppl_producto(conn, r["producto"]),
            }

    return {
        "stock_rows": _stock_rows(demo, dfs_view, con_precio=not cert),
        "stock_cols": (
            ["producto", "ing_activo", "familia", "stock", "um", "pppl", "phi"]
            if cert
            else ["producto", "ing_activo", "familia", "stock", "um", "pmp", "pppl", "phi"]
        ),
        "filtro_q": q,
        "pdf_stock_url": pdf_url,
        "pdf_stock_habilitado": not cert,
        "es_admin": demo.es_admin(),
        "stock_edit": edit_item,
        "stock_opts": [
            {"id": int(r["id"]), "label": f"{int(r['id'])} — {r['producto']} (stock: {demo.f_cantidad(r['stock'])} {r['unidad_medida']})"}
            for _, r in dfs_view.iterrows()
        ] if demo.es_admin() and not cert and not dfs_view.empty else [],
        "familias_prod": demo.listar_familias_producto(conn),
        "unidades_medida": demo.UNIDADES_MEDIDA_INSUMO,
    }


def _productos_salida(demo, conn) -> list[dict]:
    dfi = pd.read_sql_query(
        "SELECT id, producto, precio_medio, COALESCE(unidad_medida, 'kg') AS unidad_medida, stock "
        "FROM inventario WHERE stock > 0 ORDER BY producto",
        conn,
    )
    out = []
    for _, r in dfi.iterrows():
        out.append(
            {
                "id": int(r["id"]),
                "producto": r["producto"],
                "unidad_medida": r["unidad_medida"],
                "stock_fmt": demo.f_cantidad(r["stock"]),
            }
        )
    return out


def _procesar_salida(demo, conn) -> dict:
    try:
        iid = int(request.form.get("producto_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos de salida inválidos."}
    ct = parse_decimal_cl(request.form.get("cantidad"), None)
    if ct is None:
        return {"ok": False, "msg": "Cantidad inválida. Use coma decimal (ej. 1,5)."}

    ccs = [c.upper() for c in request.form.getlist("cuarteles") if c in demo.CENTROS_COSTO]
    row = conn.execute(
        "SELECT producto, precio_medio, COALESCE(unidad_medida, ?), COALESCE(stock, 0) "
        "FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, iid),
    ).fetchone()
    if not row:
        return {"ok": False, "msg": "Producto no encontrado."}
    if ct <= 0 or not ccs:
        return {"ok": False, "msg": "Indique cantidad y al menos un cuartel."}

    prod_nombre, pmp, um_sel = row[0], float(row[1] or 0), row[2]
    stock_disp = float(row[3] or 0)
    if stock_disp <= 0:
        return {"ok": False, "msg": f"Sin stock disponible de {prod_nombre}."}
    if ct > stock_disp + 1e-9:
        return {
            "ok": False,
            "msg": (
                f"Stock insuficiente: solicitó {demo.f_cantidad(ct)} {um_sel}, "
                f"disponible {demo.f_cantidad(stock_disp)} {um_sel}. No se permite saldo negativo."
            ),
        }

    for c in ccs:
        cant_cc = ct / len(ccs)
        conn.execute(
            """INSERT INTO movimientos
               (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (?,?,?,?,?,?,?)""",
            (iid, "Salida", cant_cc, str(hoy_demo(demo)), c, cant_cc * pmp, um_sel),
        )
    cur = conn.execute(
        "UPDATE inventario SET stock = stock - ? WHERE id = ? AND stock >= ?",
        (ct, iid, ct),
    )
    if cur.rowcount != 1:
        conn.rollback()
        return {
            "ok": False,
            "msg": (
                f"Stock insuficiente de {prod_nombre} "
                f"(disponible {demo.f_cantidad(stock_disp)} {um_sel}). No se permite saldo negativo."
            ),
        }
    conn.commit()
    demo.registrar_accion("BODEGA", f"{iid} - {prod_nombre}")

    if demo.producto_pppl_aprobado(conn, prod_nombre):
        session["bodega_alerta_lc"] = {
            "producto": prod_nombre,
            "cantidad": ct,
            "um": um_sel,
            "cuarteles": list(ccs),
        }
        return {"ok": True, "msg": "Salida registrada. Revise el aviso PPPL / Libro de Campo."}
    return {"ok": True, "msg": "Salida de bodega registrada correctamente."}


def _pppl(demo, conn) -> dict:
    df_aud = demo._auditar_bodega_pppl(conn)
    if df_aud.empty:
        return {
            "pppl_rows": [],
            "pppl_kpis": {},
            "puede_gestionar_pppl": demo.puede_gestionar_pppl(),
        }

    fito = df_aud[df_aud["ESTADO_COD"] != "NO_REQUIERE"]
    kpis = {
        "fitos": len(fito),
        "autorizados": len(fito[fito["ESTADO_COD"] == "AUTORIZADO"]),
        "pendientes": len(fito[fito["ESTADO_COD"] == "PENDIENTE"]),
        "desinc": len(fito[fito["ESTADO_COD"] == "DESINCronizado"]),
        "sin_ref": len(fito[fito["ESTADO_COD"] == "SIN_REFERENCIA"]),
    }
    rows = []
    edit_rows = []
    show = df_aud.drop(columns=["id"], errors="ignore")
    for _, r in df_aud.iterrows():
        estado = r.get("ESTADO_COD", "")
        inv_id = int(r["id"])
        rows.append(
            {
                "id": inv_id,
                "producto": r.get("PRODUCTO", ""),
                "familia": r.get("FAMILIA", ""),
                "estado": r.get("ESTADO", ""),
                "estado_css": _ESTADO_CSS.get(estado, "secondary"),
                "pppl_bodega": r.get("PPPL_BODEGA", ""),
                "phi_bodega": r.get("PHI_BODEGA", ""),
                "phi_sugerido": r.get("PHI_SUGERIDO", ""),
                "ingrediente": r.get("INGREDIENTE_SAG", ""),
                "confianza": r.get("CONFIANZA", ""),
            }
        )
        if estado != "NO_REQUIERE":
            phi_sug = r.get("PHI_SUGERIDO", "")
            phi_def = int(phi_sug) if str(phi_sug).isdigit() else 0
            ing = r.get("INGREDIENTE_SAG", "")
            edit_rows.append(
                {
                    "id": inv_id,
                    "producto": r.get("PRODUCTO", ""),
                    "pppl_ok": r.get("PPPL_BODEGA") == "Sí",
                    "phi_def": phi_def,
                    "ingrediente": ing if ing != "—" else "",
                    "notas": r.get("NOTAS_SAG", "") or "",
                }
            )

    pppl_edit_id = request.args.get("pppl_id")
    pppl_edit = None
    if edit_rows:
        sel = int(pppl_edit_id) if pppl_edit_id and str(pppl_edit_id).isdigit() else edit_rows[0]["id"]
        pppl_edit = next((x for x in edit_rows if x["id"] == sel), edit_rows[0])

    return {
        "pppl_rows": rows,
        "pppl_kpis": kpis,
        "puede_gestionar_pppl": demo.puede_gestionar_pppl(),
        "pppl_edit_opts": edit_rows,
        "pppl_edit": pppl_edit,
    }


def _consulta_cuartel(demo, conn) -> dict:
    hoy = hoy_demo(demo)
    ccq = request.args.get("cuartel", demo.CENTROS_COSTO[0])
    if ccq not in demo.CENTROS_COSTO:
        ccq = demo.CENTROS_COSTO[0]
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=90))
    ff = parse_date(request.args.get("hasta"), hoy)

    sql_um = demo._sql_um_movimiento()
    dfcc_raw = pd.read_sql_query(
        f"""SELECT m.id AS ID, m.producto_id AS PRODUCTO_ID, m.fecha AS FECHA, i.producto AS PRODUCTO,
                   m.cantidad AS CANTIDAD, {sql_um} AS UM, m.valor_imputado AS VALOR_IMPUTADO
            FROM movimientos m JOIN inventario i ON m.producto_id = i.id
            WHERE m.centro_costo = ? AND m.tipo = 'Salida'
              AND m.fecha BETWEEN ? AND ?
            ORDER BY m.fecha ASC, m.id ASC""",
        conn,
        params=(ccq.upper(), str(fi), str(ff)),
    )

    rows = []
    mov_opts = []
    mov_edit = None
    pdf_url = None
    if not dfcc_raw.empty:
        dfcc_show = dfcc_raw.sort_values(["FECHA", "ID"], ascending=[False, False]).reset_index(drop=True)
        dfcc_show["N"] = range(len(dfcc_show), 0, -1)
        for _, r in dfcc_show.iterrows():
            mid = int(r["ID"])
            rows.append(
                {
                    "n": int(r["N"]),
                    "id": mid,
                    "fecha": str(r["FECHA"])[:10],
                    "producto": r["PRODUCTO"],
                    "cantidad": demo.f_cantidad(r["CANTIDAD"]),
                    "cant_raw": float(r["CANTIDAD"]),
                    "um": r["UM"],
                    "valor": demo.f_peso(r["VALOR_IMPUTADO"]),
                    "valor_raw": float(r["VALOR_IMPUTADO"] or 0),
                    "producto_id": int(r["PRODUCTO_ID"]),
                }
            )
            mov_opts.append(
                {
                    "id": mid,
                    "label": (
                        f"ID {mid} · {str(r['FECHA'])[:10]} · {r['PRODUCTO']} · "
                        f"{demo.f_cantidad(r['CANTIDAD'])} {r['UM']} · {demo.f_peso(r['VALOR_IMPUTADO'])}"
                    ),
                }
            )
        mov_sel = request.args.get("mov_id")
        if mov_sel and str(mov_sel).isdigit():
            mov_edit = next((x for x in rows if x["id"] == int(mov_sel)), rows[0] if rows else None)
        elif rows:
            mov_edit = rows[0]
        if mov_edit:
            inv = conn.execute(
                "SELECT stock, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
                (demo.DEFAULT_UNIDAD_INSUMO, mov_edit["producto_id"]),
            ).fetchone()
            mov_edit["stock_inv"] = demo.f_cantidad(float(inv[0] or 0)) if inv else "0"
            mov_edit["um_inv"] = str(inv[1]) if inv else demo.DEFAULT_UNIDAD_INSUMO
        dfcc_pdf = dfcc_raw[["FECHA", "PRODUCTO", "CANTIDAD", "UM", "VALOR_IMPUTADO"]].copy()
        blob = demo.generar_pdf_blob(
            dfcc_pdf,
            f"MOVIMIENTOS BODEGA - CUARTEL {ccq.upper()} ({fi} a {ff})",
        )
        if blob:
            token = store_pdf(blob, f"bodega_cuartel_{ccq.lower().replace(' ', '_')}.pdf")
            pdf_url = url_for("modules.pdf_download", token=token)

    return {
        "consulta_rows": rows,
        "mov_opts": mov_opts,
        "mov_edit": mov_edit,
        "filtro_cuartel": ccq,
        "cuarteles": demo.CENTROS_COSTO,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_consulta_url": pdf_url,
        "es_admin": demo.es_admin(),
    }


def _apertura(demo, conn) -> dict:
    return {
        "familias_prod": demo.listar_familias_producto(conn),
        "unidades_medida": demo.UNIDADES_MEDIDA_INSUMO,
        "um_default": demo.DEFAULT_UNIDAD_INSUMO,
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
    return {
        "desfase_lc_rows": df_lc_sin.fillna("").to_dict(orient="records") if not df_lc_sin.empty else [],
        "desfase_bod_rows": df_bod_sin.fillna("").to_dict(orient="records") if not df_bod_sin.empty else [],
        "desfase_ok": len(df_lc_sin) == 0 and len(df_bod_sin) == 0,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "ventana_dias": dias_v,
    }


def _post_corregir_stock(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        iid = int(request.form.get("producto_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Valores inválidos."}
    nst = parse_decimal_cl(request.form.get("stock"), None)
    npmp = parse_decimal_cl(request.form.get("precio_medio"), None)
    if nst is None or npmp is None:
        return {"ok": False, "msg": "Valores inválidos."}
    if nst < 0:
        return {"ok": False, "msg": "El stock no puede ser negativo."}
    nprod = (request.form.get("nombre") or "").strip()
    nfam = request.form.get("familia") or ""
    num_um = request.form.get("unidad_medida") or demo.DEFAULT_UNIDAD_INSUMO
    nia = (request.form.get("ingrediente_activo") or "").strip()
    if not iid or not nprod:
        return {"ok": False, "msg": "Datos incompletos."}
    if conn.execute(
        "SELECT id FROM inventario WHERE UPPER(producto)=? AND id!=?",
        (nprod.upper(), iid),
    ).fetchone():
        return {"ok": False, "msg": "Ya existe otro producto con ese nombre."}
    conn.execute(
        "UPDATE inventario SET producto=?, familia=?, stock=?, unidad_medida=?, precio_medio=?, ingrediente_activo=? WHERE id=?",
        (nprod, nfam, nst, num_um, npmp, nia, iid),
    )
    if demo.requiere_autorizacion_pppl(nfam) and nia:
        gap = conn.execute(
            "SELECT id FROM gap_pppl WHERE UPPER(TRIM(producto))=?",
            (nprod.upper(),),
        ).fetchone()
        if gap:
            conn.execute(
                "UPDATE gap_pppl SET ingrediente_activo=?, vigente=1 WHERE id=?",
                (nia, gap[0]),
            )
    conn.commit()
    demo.registrar_accion("BODEGA", f"ID {iid} producto={nprod} stock={nst}")
    return {"ok": True, "msg": "Producto corregido.", "extra": {"edit_id": iid}}


def _post_apertura(demo, conn) -> dict:
    np = (request.form.get("nombre") or "").strip()
    nf = request.form.get("familia") or ""
    nu = request.form.get("unidad_medida") or demo.DEFAULT_UNIDAD_INSUMO
    nia = (request.form.get("ingrediente_activo") or "").strip()
    ns = parse_decimal_cl(request.form.get("stock"), None)
    npr = parse_decimal_cl(request.form.get("precio_medio"), None)
    if ns is None or npr is None:
        return {"ok": False, "msg": "Stock o PMP inválido."}
    if ns < 0:
        return {"ok": False, "msg": "El stock no puede ser negativo."}
    if not np:
        return {"ok": False, "msg": "Ingrese el nombre del producto."}
    if conn.execute("SELECT id FROM inventario WHERE UPPER(producto)=?", (np.upper(),)).fetchone():
        return {"ok": False, "msg": "El producto ya existe. Use Compras → Insumos para nuevas compras."}
    cur = conn.execute(
        "INSERT INTO inventario (producto, familia, stock, precio_medio, unidad_medida, ingrediente_activo) VALUES (?,?,?,?,?,?)",
        (np, nf, ns, npr, nu, nia),
    )
    new_id = cur.lastrowid
    if not nia:
        from erp_inventario_ia import poblar_ingredientes_inventario

        poblar_ingredientes_inventario(conn, new_id)
    elif demo.requiere_autorizacion_pppl(nf):
        gap = conn.execute(
            "SELECT id FROM gap_pppl WHERE UPPER(TRIM(producto))=?",
            (np.upper(),),
        ).fetchone()
        if gap:
            conn.execute(
                "UPDATE gap_pppl SET ingrediente_activo=?, vigente=1 WHERE id=?",
                (nia, gap[0]),
            )
    conn.commit()
    demo.registrar_accion("BODEGA", f"Apertura stock {np}")
    return {"ok": True, "msg": "Apertura de inventario registrada."}


def _post_pppl_sync(demo, conn, incluir_baja: bool = False) -> dict:
    if not demo.puede_gestionar_pppl():
        return {"ok": False, "msg": "Sin permiso para gestionar PPPL."}
    df_aud = demo._auditar_bodega_pppl(conn)
    ok, omit, err = demo._sincronizar_pppl_bodega(conn, df_aud, incluir_baja=incluir_baja)
    if ok:
        msg = f"PPPL actualizado para {len(ok)} producto(s)."
        if omit:
            msg += f" Omitidos: {len(omit)}."
        return {"ok": True, "msg": msg}
    if err:
        return {"ok": False, "msg": "; ".join(err[:3])}
    return {"ok": True, "msg": "No hay productos pendientes para sincronizar."}


def _post_pppl_manual(demo, conn) -> dict:
    if not demo.puede_gestionar_pppl():
        return {"ok": False, "msg": "Sin permiso para gestionar PPPL."}
    try:
        sel_id = int(request.form.get("producto_id") or 0)
        dias_phi = int(request.form.get("dias_carencia") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    pppl_ok = request.form.get("pppl_aprobado") == "1"
    ing_man = (request.form.get("ingrediente_activo") or "").strip()
    notas_man = (request.form.get("notas") or "").strip()
    sync_gap = request.form.get("sync_gap") == "1"
    row = conn.execute("SELECT producto FROM inventario WHERE id=?", (sel_id,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Producto no encontrado."}
    conn.execute(
        "UPDATE inventario SET pppl_aprobado=?, dias_carencia=?, ingrediente_activo=? WHERE id=?",
        (1 if pppl_ok else 0, dias_phi, ing_man, sel_id),
    )
    if sync_gap and pppl_ok:
        nom = str(row[0]).strip()
        especie = demo.GAP_ESPECIE_GENERAL
        gap = conn.execute("SELECT id FROM gap_pppl WHERE UPPER(producto)=?", (nom.upper(),)).fetchone()
        if gap:
            conn.execute(
                """UPDATE gap_pppl SET ingrediente_activo=?, dias_carencia=?, vigente=1, notas=?, especie=?
                   WHERE id=?""",
                (ing_man, dias_phi, notas_man, especie, gap[0]),
            )
        else:
            conn.execute(
                """INSERT INTO gap_pppl (producto, ingrediente_activo, dias_carencia, mercado, vigente, notas, especie)
                   VALUES (?,?,?,?,1,?,?)""",
                (nom, ing_man, dias_phi, "General", notas_man, especie),
            )
    conn.commit()
    demo.registrar_accion("BODEGA PPPL MANUAL", row[0])
    return {"ok": True, "msg": "Producto PPPL actualizado.", "extra": {"pppl_id": sel_id}}


def _post_corregir_mov(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        ide = int(request.form.get("mov_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Datos inválidos."}
    nc = parse_decimal_cl(request.form.get("cantidad"), None)
    nv = parse_decimal_cl(request.form.get("valor"), None)
    if nc is None or nv is None:
        return {"ok": False, "msg": "Cantidad o valor inválido. Use coma decimal (ej. 1,5)."}
    nf = request.form.get("fecha") or str(hoy_demo(demo))
    cuartel = (request.form.get("cuartel") or "").upper()
    if nc <= 0:
        return {"ok": False, "msg": "La cantidad debe ser mayor a cero."}
    mov = conn.execute(
        "SELECT producto_id, cantidad FROM movimientos WHERE id=? AND tipo='Salida'",
        (ide,),
    ).fetchone()
    if not mov:
        return {"ok": False, "msg": "Movimiento no encontrado."}
    pid, old_c = int(mov[0]), float(mov[1])
    inv = conn.execute(
        "SELECT stock, COALESCE(unidad_medida, ?) FROM inventario WHERE id=?",
        (demo.DEFAULT_UNIDAD_INSUMO, pid),
    ).fetchone()
    stock_inv = float(inv[0] or 0) if inv else 0.0
    um_inv = str(inv[1] if inv else demo.DEFAULT_UNIDAD_INSUMO)
    delta_stock = old_c - nc
    # Aumentar salida (= bajar stock) no puede dejar saldo negativo.
    if delta_stock < 0 and stock_inv + delta_stock < -1e-9:
        return {
            "ok": False,
            "msg": (
                f"Stock insuficiente para aumentar la salida "
                f"(disponible: {demo.f_cantidad(stock_inv)} {um_inv}). No se permite saldo negativo."
            ),
        }
    conn.execute(
        "UPDATE movimientos SET fecha=?, cantidad=?, valor_imputado=?, unidad_medida=? WHERE id=?",
        (nf, nc, nv, um_inv, ide),
    )
    if delta_stock != 0:
        if delta_stock < 0:
            cur = conn.execute(
                "UPDATE inventario SET stock = stock + ? WHERE id=? AND stock >= ?",
                (delta_stock, pid, -delta_stock),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return {
                    "ok": False,
                    "msg": (
                        f"Stock insuficiente (disponible: {demo.f_cantidad(stock_inv)} {um_inv}). "
                        "No se permite saldo negativo."
                    ),
                }
        else:
            conn.execute("UPDATE inventario SET stock = stock + ? WHERE id=?", (delta_stock, pid))
    conn.commit()
    demo.registrar_accion("BODEGA", f"Corrección salida ID {ide} cuartel {cuartel}")
    return {
        "ok": True,
        "msg": f"Salida corregida: {demo.f_cantidad(nc)} {um_inv}.",
        "extra": {"cuartel": cuartel, "mov_id": ide, "desde": request.form.get("desde", ""), "hasta": request.form.get("hasta", "")},
    }


def _post_eliminar_mov(demo, conn) -> dict:
    if not demo.es_admin():
        return {"ok": False, "msg": "Requiere perfil admin."}
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    try:
        ide = int(request.form.get("mov_id") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Movimiento inválido."}
    cuartel = (request.form.get("cuartel") or "").upper()
    mov = conn.execute(
        """SELECT m.producto_id, m.cantidad, COALESCE(m.unidad_medida, ?) AS um
           FROM movimientos m WHERE m.id=? AND m.tipo='Salida'""",
        (demo.DEFAULT_UNIDAD_INSUMO, ide),
    ).fetchone()
    if not mov:
        return {"ok": False, "msg": "Movimiento no encontrado."}
    pid, cant, um = int(mov[0]), float(mov[1]), mov[2]
    conn.execute("DELETE FROM movimientos WHERE id=?", (ide,))
    conn.execute("UPDATE inventario SET stock = stock + ? WHERE id=?", (cant, pid))
    conn.commit()
    demo.registrar_accion("BODEGA", f"Eliminada salida ID {ide}")
    return {
        "ok": True,
        "msg": f"Salida eliminada. Se repusieron {demo.f_cantidad(cant)} {um} en bodega.",
        "extra": {"cuartel": cuartel, "desde": request.form.get("desde", ""), "hasta": request.form.get("hasta", "")},
    }


def gather_bodega(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    secciones = _secciones(demo)
    sec = request.args.get("sec", secciones[0][0])
    if sec not in {k for k, _ in secciones}:
        sec = secciones[0][0]

    conn = demo.conectar_db()
    try:
        ctx: dict = {
            "secciones": secciones,
            "sec_activa": sec,
            "es_certificacion": demo.es_certificacion(),
            **_pop_alertas(),
        }
        if sec == "stock":
            ctx.update(_stock(demo, conn, cert=demo.es_certificacion()))
        elif sec == "salida":
            ctx["productos_salida"] = _productos_salida(demo, conn)
            ctx["cuarteles"] = demo.CENTROS_COSTO
        elif sec == "pppl":
            ctx.update(_pppl(demo, conn))
        elif sec == "apertura":
            ctx.update(_apertura(demo, conn))
        elif sec == "consulta":
            ctx.update(_consulta_cuartel(demo, conn))
        elif sec == "desfase":
            ctx.update(_desfase(demo, conn))
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "stock")
        conn = demo.conectar_db()
        try:
            handlers = {
                "salida": _procesar_salida,
                "corregir_stock": _post_corregir_stock,
                "apertura": _post_apertura,
                "pppl_sync_ok": lambda d, c: _post_pppl_sync(d, c, incluir_baja=False),
                "pppl_sync_all": lambda d, c: _post_pppl_sync(d, c, incluir_baja=True),
                "pppl_manual": _post_pppl_manual,
                "corregir_mov": _post_corregir_mov,
                "eliminar_mov": _post_eliminar_mov,
            }
            fn = handlers.get(action)
            if fn:
                result = fn(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec}
                extra.update(result.get("extra") or {})
                if action == "corregir_stock" and "edit_id" not in extra:
                    extra["edit_id"] = request.form.get("producto_id", "")
                if action == "pppl_manual" and "pppl_id" not in extra:
                    extra["pppl_id"] = request.form.get("producto_id", "")
                if action in ("corregir_mov", "eliminar_mov"):
                    for k in ("cuartel", "desde", "hasta"):
                        if k not in extra and request.form.get(k):
                            extra[k] = request.form.get(k)
                if action == "corregir_mov" and "mov_id" not in extra:
                    extra["mov_id"] = request.form.get("mov_id", "")
                if request.form.get("q"):
                    extra["q"] = request.form.get("q")
                return _redirect_bodega(**extra)
        finally:
            conn.close()

    ctx = gather_bodega(user_email, user_rol)
    return render_template(
        "modules/bodega.html",
        page_title="Bodega",
        active_key="Bodega",
        title="🏠 Bodega",
        **ctx,
    )
