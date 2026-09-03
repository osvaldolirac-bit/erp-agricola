from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.lc_excluir_espino import filtrar_df_facturas_espino_lc, sql_and_excluir_razon_social_espino
from demo_web.services.native._helpers import hoy_demo
from demo_web.services.tenant_scope import razon_social_default

SECCIONES = [
    ("pendientes", "🔴 PENDIENTES"),
    ("deuda", "🏢 DEUDA POR PROVEEDOR"),
    ("historial", "📜 HISTORIAL AUDITABLE"),
]

METODOS_PAGO = ["Transferencia", "Efectivo", "Cheque", "Tarjeta bancaria"]
METODOS_CON_BANCO = {"Transferencia", "Cheque", "Tarjeta bancaria"}

BANCOS_PAGO = [
    "—",
    "Banco Estado",
    "Banco de Chile",
    "Banco Santander",
    "BCI",
    "Scotiabank",
    "Itaú",
    "Banco BICE",
    "Banco Security",
    "Banco Falabella",
    "Banco Ripley",
    "Banco Internacional",
    "Otro",
]


def _banco_form(metodo: str = "") -> str:
    """Banco aplica para Transferencia, Cheque y Tarjeta bancaria."""
    if metodo not in METODOS_CON_BANCO:
        return ""
    banco = (request.form.get("banco") or "").strip()
    if banco in ("", "—", "-"):
        return ""
    if banco not in BANCOS_PAGO:
        return banco[:80]
    return banco


def _validar_banco_pago(metodo: str, banco: str) -> str | None:
    if metodo in METODOS_CON_BANCO and not banco:
        return "Seleccione el banco para Transferencia, Cheque o Tarjeta bancaria."
    return None


def _demo():
    return get_demo_module()


def _sec_key(label: str) -> str:
    for key, lbl in SECCIONES:
        if lbl == label:
            return key
    return SECCIONES[0][0]


def _sec_label(key: str) -> str:
    for k, lbl in SECCIONES:
        if k == key:
            return lbl
    return SECCIONES[0][1]


def _parse_date(val: str | None, default: date) -> date:
    if not val:
        return default
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return default


def _proveedor_contacto_html(conn, nombre: str) -> str | None:
    try:
        from erp_proveedores import obtener_proveedor_por_nombre

        prov = obtener_proveedor_por_nombre(conn, nombre)
    except Exception:
        prov = None
    if not prov:
        return None
    partes = []
    if prov.get("contacto"):
        partes.append(f"<strong>Contacto:</strong> {prov['contacto']}")
    if prov.get("email"):
        partes.append(f"<strong>Mail:</strong> {prov['email']}")
    if prov.get("telefono"):
        partes.append(f"<strong>Teléfono:</strong> {prov['telefono']}")
    if prov.get("celular"):
        partes.append(f"<strong>Celular:</strong> {prov['celular']}")
    if not partes:
        return None
    return (
        "<div class='alert alert-light border mb-3 py-2 small'>"
        "🏢 <strong>Proveedor</strong> · " + " · ".join(partes) + "</div>"
    )


def _pdf_url(demo, blob, archivo: str) -> str | None:
    if not blob:
        return None
    token = store_pdf(blob, archivo)
    return url_for("modules.pdf_download", token=token)


def _pendientes_pdf(demo, conn, hoy: date) -> str | None:
    dfp = filtrar_df_facturas_espino_lc(
        demo._cargar_facturas_pendientes_saldo(conn)
    ).sort_values("fecha_vencimiento")
    if dfp.empty:
        return None
    dfp_show = dfp.rename(columns={
        "nro_documento": "N° DOCUMENTO",
        "proveedor": "PROVEEDOR",
        "razon_social": "RAZÓN SOCIAL",
        "fecha_vencimiento": "VENCIMIENTO",
        "dias_vencido": "DÍAS VENC.",
        "monto_total": "MONTO DOC.",
        "monto_pagado": "ABONADO",
        "saldo": "SALDO",
    }).drop(columns=["id"], errors="ignore")
    dfp_show = dfp_show[
        [
            "N° DOCUMENTO", "PROVEEDOR", "RAZÓN SOCIAL", "VENCIMIENTO", "DÍAS VENC.",
            "MONTO DOC.", "ABONADO", "SALDO",
        ]
    ]
    estilo = getattr(demo, "_pdf_estilo_tesoreria_vencida", None)
    blob = demo.generar_pdf_blob(
        dfp_show,
        "DEUDAS PENDIENTES",
        campo_suma_forzado="SALDO",
        estilo_celda_fn=estilo,
        font_size_header=12,
        font_size_body=11,
        h_line_header=10,
        h_line_body=7,
    )
    return _pdf_url(demo, blob, "pendientes.pdf")


def _deuda_pdf(demo, conn, proveedor: str) -> str | None:
    dfpr = pd.read_sql_query(
        f"""SELECT nro_documento, fecha_vencimiento, monto_total,
                  COALESCE(monto_pagado, 0) AS monto_pagado
           FROM facturas
           WHERE proveedor=? AND estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0
           {sql_and_excluir_razon_social_espino()}
           ORDER BY fecha_vencimiento ASC""",
        conn,
        params=(proveedor,),
    )
    if dfpr.empty:
        return None
    dfpr["saldo_pendiente"] = dfpr.apply(
        lambda r: demo._saldo_pendiente_factura(r["monto_total"], r["monto_pagado"]),  # noqa: SLF001
        axis=1,
    )
    dfpr = dfpr[dfpr["saldo_pendiente"] > 0.01].copy()
    if dfpr.empty:
        return None
    dfpr_show = dfpr.rename(columns={
        "monto_total": "monto_doc",
        "monto_pagado": "abonado",
    })
    estilo = getattr(demo, "_pdf_estilo_tesoreria_vencida", None)
    blob = demo.generar_pdf_blob(
        dfpr_show,
        f"DEUDA {proveedor}",
        campo_suma_forzado="saldo_pendiente",
        estilo_celda_fn=estilo,
    )
    safe = proveedor.lower().replace(" ", "_")[:40]
    return _pdf_url(demo, blob, f"deuda_{safe}.pdf")


def _historial_pdf(demo, conn, fi: date, ff: date, bsq: str, met: str) -> str | None:
    dfh = filtrar_df_facturas_espino_lc(
        demo._query_historial_abonos_tesoreria(conn, fi, ff, bsq, met)
    )
    if dfh.empty:
        return None
    fn = getattr(demo, "generar_pdf_tesoreria_pagos", None)
    blob = fn(dfh) if fn else None
    return _pdf_url(demo, blob, "pagos_tesoreria.pdf")


def _pendientes_rows(demo, conn, hoy: date) -> tuple[list[dict], str, int]:
    dfp = filtrar_df_facturas_espino_lc(
        demo._cargar_facturas_pendientes_saldo(conn)
    ).sort_values("fecha_vencimiento")
    if dfp.empty:
        return [], demo.f_peso(0), 0
    total = demo.f_peso(dfp["saldo"].sum())
    rows = []
    for _, r in dfp.iterrows():
        venc = pd.to_datetime(r["fecha_vencimiento"]).date()
        vencido = venc < hoy
        rows.append(
            {
                "nro_documento": r["nro_documento"],
                "proveedor": r["proveedor"],
                "razon_social": r.get("razon_social") or razon_social_default(),
                "fecha_vencimiento": venc.strftime("%d-%m-%Y"),
                "dias_vencido": "" if pd.isna(r.get("dias_vencido")) else int(r["dias_vencido"]),
                "monto_total": demo.f_peso(r["monto_total"]),
                "monto_pagado": demo.f_peso(r["monto_pagado"]),
                "saldo": demo.f_peso(r["saldo"]),
                "vencido": vencido,
            }
        )
    return rows, total, len(rows)


def _deuda_rows(demo, conn, proveedor: str | None) -> tuple[list[str], list[dict], str | None, str]:
    excl = sql_and_excluir_razon_social_espino()
    prvs = pd.read_sql_query(
        f"""SELECT DISTINCT proveedor FROM facturas
           WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0
           {excl}
           ORDER BY proveedor""",
        conn,
    )
    proveedores = prvs["proveedor"].tolist() if not prvs.empty else []
    if not proveedores:
        return [], [], None, ""
    psel = proveedor if proveedor in proveedores else proveedores[0]
    dfpr = pd.read_sql_query(
        f"""SELECT id, nro_documento, fecha_vencimiento, monto_total,
                  COALESCE(monto_pagado, 0) AS monto_pagado,
                  COALESCE(NULLIF(TRIM(razon_social), ''), '') AS razon_social
           FROM facturas
           WHERE proveedor=? AND estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0
           {excl}
           ORDER BY fecha_vencimiento ASC""",
        conn,
        params=(psel,),
    )
    dfpr["saldo"] = dfpr.apply(
        lambda r: demo._saldo_pendiente_factura(r["monto_total"], r["monto_pagado"]),  # noqa: SLF001
        axis=1,
    )
    dfpr = dfpr[dfpr["saldo"] > 0.01].copy()
    rows = []
    for _, r in dfpr.iterrows():
        saldo_f = float(r["saldo"])
        abonado_f = float(r["monto_pagado"])
        rows.append(
            {
                "id": int(r["id"]),
                "nro_documento": r["nro_documento"],
                "fecha_vencimiento": pd.to_datetime(r["fecha_vencimiento"]).strftime("%d-%m-%Y"),
                "monto_total": demo.f_peso(r["monto_total"]),
                "monto_pagado": demo.f_peso(abonado_f),
                "saldo": demo.f_peso(saldo_f),
                "saldo_raw": saldo_f,
                "monto_pagado_raw": abonado_f,
            }
        )
    contacto = _proveedor_contacto_html(conn, psel)
    resumen = (
        f"Deuda con {psel}: {demo.f_peso(dfpr['saldo'].sum())} — {len(dfpr)} documento(s) pendiente(s)"
        if not dfpr.empty
        else f"Sin deuda pendiente con {psel}."
    )
    return proveedores, rows, contacto, resumen


def _historial_grupos(demo, conn, fi: date, ff: date, bsq: str, met: str) -> tuple[list[dict], dict]:
    dfh = filtrar_df_facturas_espino_lc(
        demo._query_historial_abonos_tesoreria(conn, fi, ff, bsq, met)
    )
    if dfh.empty:
        return [], {"pagos": 0, "docs": 0, "total": demo.f_peso(0)}
    df_p = dfh.copy()
    if "banco" not in df_p.columns:
        df_p["banco"] = ""
    else:
        df_p["banco"] = df_p["banco"].fillna("").astype(str)
    df_p = df_p.sort_values(
        ["fecha_pago", "proveedor", "metodo_pago", "banco", "nro_documento"],
        ascending=[True, True, True, True, True],
    )
    grupos_raw = list(df_p.groupby(["proveedor", "fecha_pago", "metodo_pago", "banco"], sort=False))
    total_periodo = float(dfh["monto_total"].sum())
    grupos = []
    for num, ((prov, f_pago, metodo, banco), grp) in reversed(list(enumerate(grupos_raw, start=1))):
        detalle = []
        for _, row in grp.iterrows():
            item = {
                "nro_documento": row["nro_documento"],
                "monto": demo.f_peso(row["monto_total"]),
            }
            if "razon_social" in grp.columns:
                item["razon_social"] = row.get("razon_social") or ""
            detalle.append(item)
        grupos.append(
            {
                "num": num,
                "proveedor": prov,
                "fecha_pago": str(f_pago),
                "metodo": metodo,
                "banco": (banco or "").strip(),
                "total": demo.f_peso(float(grp["monto_total"].sum())),
                "n_docs": len(grp),
                "detalle": detalle,
            }
        )
    stats = {
        "pagos": len(grupos_raw),
        "docs": len(dfh),
        "total": demo.f_peso(total_periodo),
    }
    return grupos, stats


def _redirect_tesoreria(sec: str, **extra):
    params = {"sec": sec, **{k: str(v) for k, v in extra.items() if v is not None and v != ""}}
    return redirect_module("tesoreria", **params)


def _enviar_correo_pago_interno(demo, conn, proveedor, documentos, monto_total, metodo, usuario_operador, banco="", razon_social=""):
    from erp_correo_html import html_esc, plantilla_correo_html
    from erp_proveedores import razones_sociales_desde_docs

    destinatarios = demo.obtener_destinatarios_tesoreria(conn)
    if not destinatarios:
        return False
    filas_docs = "".join(
        f"<p>📄 <b>{html_esc(d['nro_documento'])}</b> — ${int(d['monto']):,}</p>"
        for d in documentos
    )
    n_docs = len(documentos)
    linea_banco = f"<p><b>🏦 Banco:</b> {html_esc(banco)}</p>" if banco else ""
    pagador = razones_sociales_desde_docs(documentos, razon_social) or ""
    marca_erp = (getattr(demo, "NOMBRE_ERP", None) or "ERP Agrícola").strip()
    linea_razon = (
        f"<p><b>🏛️ Razón social que paga:</b> {html_esc(pagador)}</p>"
        if pagador else ""
    )
    interior = f"""
                    <p>Se ha procesado un movimiento conforme en el módulo de <b>Tesorería</b>:</p>
                    <hr style='border: 0; border-top: 1px solid #eee;'>
                    {linea_razon}
                    <p><b>🏢 Proveedor:</b> {html_esc(proveedor)}</p>
                    <p><b>📄 Documento(s) pagado(s):</b> {n_docs}</p>
                    {filas_docs}
                    <p><b>💰 Monto total pagado:</b> <span style='font-weight: bold;'>${int(monto_total):,}</span></p>
                    <p><b>💳 Forma de pago:</b> {html_esc(metodo)}</p>
                    {linea_banco}
                    <p><b>👤 Usuario Operador:</b> <span style='font-weight: bold;'>{html_esc(usuario_operador)}</span></p>
                    <p><b>📅 Fecha:</b> {str(hoy_demo(demo))}</p>
    """
    cuerpo_html = plantilla_correo_html(
        "tesoreria",
        "💸 Egreso registrado en Tesorería",
        interior,
        nombre_erp=marca_erp,
        pie="Respaldo automático de auditoría — Tesorería.",
    )
    return demo._enviar_correo_html(
        f"🚨 [{marca_erp}] Pago Procesado: {proveedor} ({n_docs} doc.)",
        cuerpo_html,
        destinatarios,
    )


def _docs_pendientes_proveedor(demo, conn, proveedor: str) -> pd.DataFrame:
    dfpr = pd.read_sql_query(
        f"""SELECT id, nro_documento, fecha_vencimiento, monto_total,
                  COALESCE(monto_pagado, 0) AS monto_pagado,
                  COALESCE(NULLIF(TRIM(razon_social), ''), '') AS razon_social
           FROM facturas
           WHERE proveedor=? AND estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0
           {sql_and_excluir_razon_social_espino()}
           ORDER BY fecha_vencimiento ASC""",
        conn,
        params=(proveedor,),
    )
    if dfpr.empty:
        return dfpr
    dfpr["saldo"] = dfpr.apply(
        lambda r: demo._saldo_pendiente_factura(r["monto_total"], r["monto_pagado"]),  # noqa: SLF001
        axis=1,
    )
    return dfpr[dfpr["saldo"] > 0.01].copy()


def _enriquecer_razon_social_lineas(conn, lineas: list) -> list:
    """Completa razon_social desde facturas si no vino en la línea."""
    out = []
    for d in lineas or []:
        item = dict(d or {})
        rs = str(item.get("razon_social") or "").strip()
        if not rs:
            nro = str(item.get("nro_documento") or "").strip()
            if nro:
                try:
                    row = conn.execute(
                        "SELECT COALESCE(NULLIF(TRIM(razon_social), ''), '') "
                        "FROM facturas WHERE nro_documento=? "
                        "AND IFNULL(nro_documento,'') NOT LIKE '%_P' "
                        "ORDER BY id DESC LIMIT 1",
                        (nro,),
                    ).fetchone()
                    rs = str((row[0] if row else "") or "").strip()
                except Exception:
                    rs = ""
            item["razon_social"] = rs
        out.append(item)
    return out


def _avisos_pago(demo, conn, proveedor, lineas, monto_total, metodo, fecha_pago, enviar_mail: bool, usuario: str, banco=""):
    from erp_proveedores import (
        enviar_correo_pago_proveedor_si_corresponde,
        mensaje_avisos_pago_proveedor,
        razones_sociales_desde_docs,
    )
    from erp_whatsapp import enviar_whatsapp_pago_si_corresponde

    lineas = _enriquecer_razon_social_lineas(conn, lineas)
    razon = razones_sociales_desde_docs(lineas)
    mail_ok = False
    if enviar_mail:
        mail_ok = _enviar_correo_pago_interno(
            demo, conn, proveedor, lineas, monto_total, metodo, usuario, banco=banco, razon_social=razon,
        )
    mail_prov_ok, mail_prov = enviar_correo_pago_proveedor_si_corresponde(
        conn,
        proveedor,
        lineas,
        monto_total,
        metodo,
        fecha_pago,
        demo.NOMBRE_ERP,
        demo._enviar_correo_html,
        registrar_accion=demo.registrar_accion,
        razon_social=razon,
    )
    wa_ok, wa_dest, wa_err = enviar_whatsapp_pago_si_corresponde(
        conn,
        proveedor,
        lineas,
        monto_total,
        metodo,
        fecha_pago,
        demo.NOMBRE_ERP,
        secrets_path=demo.SECRETS_PATH,
        registrar_accion=demo.registrar_accion,
        razon_social=razon,
    )
    return mail_ok, mensaje_avisos_pago_proveedor(conn, proveedor, mail_prov_ok, mail_prov, wa_ok, wa_dest, wa_err)


def _post_pagar_documentos(demo, conn, user_email: str) -> dict:
    proveedor = (request.form.get("proveedor") or "").strip()
    if not proveedor:
        return {"ok": False, "msg": "Seleccione un proveedor.", "extra": {"sec": "deuda"}}
    try:
        ids_pagar = [int(x) for x in request.form.getlist("doc_ids") if x]
    except ValueError:
        ids_pagar = []
    if not ids_pagar:
        return {"ok": False, "msg": "Seleccione al menos un documento para pagar.", "extra": {"sec": "deuda", "proveedor": proveedor}}
    metodo = request.form.get("metodo_pago") or METODOS_PAGO[0]
    if metodo not in METODOS_PAGO:
        metodo = METODOS_PAGO[0]
    banco = _banco_form(metodo)
    err_banco = _validar_banco_pago(metodo, banco)
    if err_banco:
        return {"ok": False, "msg": err_banco, "extra": {"sec": "deuda", "proveedor": proveedor}}
    fpago = _parse_date(request.form.get("fecha_pago"), hoy_demo(demo))
    enviar_mail = request.form.get("enviar_mail") == "1"
    dfpr = _docs_pendientes_proveedor(demo, conn, proveedor)
    if dfpr.empty:
        return {"ok": False, "msg": f"No hay documentos pendientes con {proveedor}.", "extra": {"sec": "deuda", "proveedor": proveedor}}
    ids_validos = set(int(i) for i in dfpr["id"].tolist())
    lineas = []
    errores = []
    monto_total = 0.0
    for doc_id in ids_pagar:
        if doc_id not in ids_validos:
            errores.append(f"Documento ID {doc_id} no pertenece a {proveedor}.")
            continue
        fila_p = dfpr[dfpr["id"] == doc_id].iloc[0]
        saldo_p = float(fila_p["saldo"])
        ok, res = demo._registrar_abono_factura(  # noqa: SLF001
            conn, doc_id, fpago, saldo_p, metodo, user_email, banco=banco,
        )
        if not ok:
            errores.append(f"{fila_p['nro_documento']}: {res}")
            continue
        lineas.append({
            "nro_documento": fila_p["nro_documento"],
            "monto": saldo_p,
            "razon_social": str((fila_p["razon_social"] if hasattr(fila_p, "index") and "razon_social" in fila_p.index else "") or "").strip(),
        })
        monto_total += saldo_p
    if not lineas:
        msg = " ".join(errores) if errores else "No se pudo registrar ningún pago."
        return {"ok": False, "msg": msg, "extra": {"sec": "deuda", "proveedor": proveedor}}
    conn.commit()
    mail_ok, avisos = _avisos_pago(demo, conn, proveedor, lineas, monto_total, metodo, fpago, enviar_mail, user_email, banco=banco)
    docs_txt = ", ".join(d["nro_documento"] for d in lineas)
    det_banco = f" | {banco}" if banco else ""
    demo.registrar_accion("PAGO PROVEEDOR", f"{proveedor}: {docs_txt} | {metodo}{det_banco}")
    msg = f"✅ {len(lineas)} documento(s) de {proveedor} pagados por {demo.f_peso(monto_total)}."
    if banco:
        msg += f" Banco: {banco}."
    if enviar_mail:
        msg += " Correo de respaldo enviado al equipo." if mail_ok else " Pago registrado; no se pudo enviar el correo al equipo."
    msg += avisos
    if errores:
        msg += " Advertencias: " + " ".join(errores)
    return {"ok": True, "msg": msg, "extra": {"sec": "deuda", "proveedor": proveedor}}


def _post_abono_parcial(demo, conn, user_email: str) -> dict:
    proveedor = (request.form.get("proveedor") or "").strip()
    if not proveedor:
        return {"ok": False, "msg": "Seleccione un proveedor.", "extra": {"sec": "deuda"}}
    try:
        doc_id = int(request.form.get("doc_id") or 0)
        monto_ab = float(request.form.get("monto_abono") or 0)
    except ValueError:
        return {"ok": False, "msg": "Datos de abono inválidos.", "extra": {"sec": "deuda", "proveedor": proveedor}}
    metodo = request.form.get("metodo_pago") or METODOS_PAGO[0]
    if metodo not in METODOS_PAGO:
        metodo = METODOS_PAGO[0]
    banco = _banco_form(metodo)
    err_banco = _validar_banco_pago(metodo, banco)
    if err_banco:
        return {"ok": False, "msg": err_banco, "extra": {"sec": "deuda", "proveedor": proveedor}}
    fpago = _parse_date(request.form.get("fecha_pago"), hoy_demo(demo))
    enviar_mail = request.form.get("enviar_mail") == "1"
    dfpr = _docs_pendientes_proveedor(demo, conn, proveedor)
    if doc_id not in set(int(i) for i in dfpr["id"].tolist()):
        return {"ok": False, "msg": "Documento no válido para este proveedor.", "extra": {"sec": "deuda", "proveedor": proveedor}}
    fila_ab = dfpr[dfpr["id"] == doc_id].iloc[0]
    ok, res = demo._registrar_abono_factura(  # noqa: SLF001
        conn, doc_id, fpago, monto_ab, metodo, user_email, banco=banco,
    )
    if not ok:
        return {"ok": False, "msg": str(res), "extra": {"sec": "deuda", "proveedor": proveedor}}
    conn.commit()
    rs_ab = ""
    if hasattr(fila_ab, "index") and "razon_social" in fila_ab.index:
        rs_ab = str(fila_ab["razon_social"] or "").strip()
    lineas = [{
        "nro_documento": res["nro_documento"],
        "monto": res["monto"],
        "razon_social": rs_ab,
    }]
    mail_ok, avisos = _avisos_pago(demo, conn, proveedor, lineas, res["monto"], metodo, fpago, enviar_mail, user_email, banco=banco)
    det_banco = f" | {banco}" if banco else ""
    demo.registrar_accion(
        "ABONO FACTURA",
        f"{proveedor} | {res['nro_documento']} | {demo.f_peso(res['monto'])} | {metodo}{det_banco}",
    )
    msg = f"✅ Abono de {demo.f_peso(res['monto'])} registrado en {res['nro_documento']}."
    if banco:
        msg += f" Banco: {banco}."
    if res["estado"] == "Pagado":
        msg += " Documento saldado."
    else:
        msg += f" Saldo restante: {demo.f_peso(res['saldo_restante'])}."
    if enviar_mail:
        msg += " Correo de respaldo enviado al equipo." if mail_ok else " No se pudo enviar el correo al equipo."
    msg += avisos
    return {"ok": True, "msg": msg, "extra": {"sec": "deuda", "proveedor": proveedor}}


def gather_tesoreria(user_email: str, user_rol: str) -> dict:
    demo = _demo()
    bind_user_session(user_email, user_rol)
    hoy = hoy_demo(demo)
    sec = request.args.get("sec", SECCIONES[0][0])
    if sec not in {k for k, _ in SECCIONES}:
        sec = SECCIONES[0][0]

    conn = demo.conectar_db()
    try:
        ctx: dict = {
            "secciones": SECCIONES,
            "sec_activa": sec,
            "sec_label": _sec_label(sec),
        }
        if sec == "pendientes":
            rows, total, n = _pendientes_rows(demo, conn, hoy)
            ctx.update({
                "pendientes": rows,
                "deuda_total": total,
                "n_pendientes": n,
                "pdf_pendientes_url": _pendientes_pdf(demo, conn, hoy),
            })
        elif sec == "deuda":
            prov = request.args.get("proveedor") or None
            proveedores, rows, contacto, resumen = _deuda_rows(demo, conn, prov)
            psel = prov or (proveedores[0] if proveedores else "")
            ctx.update(
                {
                    "proveedores": proveedores,
                    "proveedor_sel": psel,
                    "deuda_rows": rows,
                    "contacto_html": contacto,
                    "deuda_resumen": resumen,
                    "metodos_pago": METODOS_PAGO,
                    "bancos": BANCOS_PAGO,
                    "hoy": hoy.isoformat(),
                    "pdf_deuda_url": _deuda_pdf(demo, conn, psel) if psel else None,
                }
            )
        else:
            fi_def = demo._fecha_minima_historial_tesoreria(conn)
            fi = _parse_date(request.args.get("desde"), fi_def)
            ff = _parse_date(request.args.get("hasta"), hoy)
            bsq = (request.args.get("q") or "").strip()
            met = request.args.get("metodo") or "TODOS"
            if met not in ["TODOS"] + METODOS_PAGO:
                met = "TODOS"
            grupos, stats = _historial_grupos(demo, conn, fi, ff, bsq, met)
            ctx.update(
                {
                    "historial_grupos": grupos,
                    "historial_stats": stats,
                    "filtro_q": bsq,
                    "filtro_metodo": met,
                    "filtro_desde": fi.isoformat(),
                    "filtro_hasta": ff.isoformat(),
                    "metodos_pago": METODOS_PAGO,
                    "pdf_historial_url": _historial_pdf(demo, conn, fi, ff, bsq, met),
                }
            )
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = _demo()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "deuda")
        conn = demo.conectar_db()
        try:
            handlers = {
                "pagar_documentos": lambda d, c: _post_pagar_documentos(d, c, user_email),
                "abono_parcial": lambda d, c: _post_abono_parcial(d, c, user_email),
            }
            fn = handlers.get(action)
            if fn:
                result = fn(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = result.get("extra") or {"sec": sec}
                return _redirect_tesoreria(**extra)
        finally:
            conn.close()

    ctx = gather_tesoreria(user_email, user_rol)
    return render_template(
        "modules/tesoreria.html",
        page_title="Tesorería",
        active_key="Tesoreria",
        title="💸 Tesorería",
        **ctx,
    )
