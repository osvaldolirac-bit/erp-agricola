from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, session, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("personal", "📋 PERSONAL"),
    ("contratistas", "🤝 CONTRATISTAS"),
    ("remuneraciones", "💼 REMUNERACIONES"),
    ("liquidacion", "💸 LIQUIDACIÓN MENSUAL"),
    ("historial", "📜 HISTORIAL PAGOS"),
]

CONTRATISTAS_SEC = [
    ("maestro", "📇 Maestro"),
    ("servicio", "📝 Registrar servicio"),
    ("por_cc", "📊 Por centro de costo"),
    ("cuenta", "📒 Cuenta corriente"),
]

MESES = [f"{i:02d}" for i in range(1, 13)]


def _fechas_con_reset_cc(cc_u: str, fi_def, ff_def, session_key: str):
    """Al cambiar CC, ignora fechas guardadas en URL (misma lógica que Streamlit)."""
    prev = session.get(session_key)
    cc_changed = prev != cc_u
    session[session_key] = cc_u
    if cc_changed:
        return fi_def, ff_def
    return parse_date(request.args.get("desde"), fi_def), parse_date(request.args.get("hasta"), ff_def)


def _check_master(demo, clave: str) -> bool:
    return (clave or "").strip() == demo.CLAVE_MAESTRA


def _redirect_rrhh(sec: str, **extra) -> redirect_module:
    return redirect_module("rrhh", sec=sec, **extra)


def migrar_personal_salida_petroleo(conn) -> None:
    """Columna de autorización para el formulario QR de salida de petróleo."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(personal)").fetchall()}
    if "autorizado_salida_petroleo" not in cols:
        conn.execute(
            "ALTER TABLE personal ADD COLUMN autorizado_salida_petroleo INTEGER DEFAULT 0"
        )
        conn.commit()


def _personal(demo, conn) -> dict:
    migrar_personal_salida_petroleo(conn)
    df = pd.read_sql_query(
        """SELECT id, nombre, rut, cargo, COALESCE(estado, 'Activo') AS estado, fecha_contrato,
                  COALESCE(autorizado_salida_petroleo, 0) AS autorizado_salida_petroleo
           FROM personal ORDER BY nombre""",
        conn,
    )
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "id": int(r["id"]),
                "nombre": r["nombre"],
                "rut": r["rut"],
                "cargo": r["cargo"] or "",
                "estado": r["estado"],
                "fecha_contrato": str(r["fecha_contrato"] or "")[:10],
                "autorizado_salida_petroleo": bool(int(r["autorizado_salida_petroleo"] or 0)),
            }
        )
    edit_id = request.args.get("edit_id")
    edit_item = next((x for x in rows if str(x["id"]) == edit_id), rows[0] if rows else None)
    activos = sum(1 for x in rows if str(x["estado"]).lower() == "activo")
    return {
        "personal_rows": rows,
        "n_personal": len(rows),
        "n_activos": activos,
        "personal_edit": edit_item,
        "hoy": demo.hoy.isoformat(),
    }


def _contratistas_maestro(demo, conn) -> dict:
    df = pd.read_sql_query(
        """SELECT id, rut, razon_social, rubro, contacto, email, celular,
                  COALESCE(mail_pago, 0) AS mail_pago, COALESCE(whatsapp_pago, 0) AS whatsapp_pago,
                  cc_habitual, estado, COALESCE(notas, '') AS notas
           FROM contratistas ORDER BY razon_social""",
        conn,
    )
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "id": int(r["id"]),
                "rut": r["rut"] or "",
                "razon_social": r["razon_social"],
                "rubro": r["rubro"] or "",
                "contacto": r["contacto"] or "",
                "mail": r["email"] or "",
                "celular": r["celular"] or "",
                "mail_pago": "Sí" if r["mail_pago"] else "No",
                "wa_pago": "Sí" if r["whatsapp_pago"] else "No",
                "mail_pago_bool": bool(r["mail_pago"]),
                "wa_pago_bool": bool(r["whatsapp_pago"]),
                "cc_habitual": r["cc_habitual"] or "",
                "estado": r["estado"] or "",
                "notas": r["notas"] or "",
            }
        )
    edit_id = request.args.get("edit_id")
    edit_item = next((x for x in rows if str(x["id"]) == edit_id), rows[0] if rows else None)
    return {
        "contratistas_rows": rows,
        "n_contratistas": len(rows),
        "contratista_edit": edit_item,
        "centros_costo": demo.CENTROS_COSTO,
    }


def _contratistas_servicio(demo, conn) -> dict:
    df = pd.read_sql_query(
        "SELECT id, razon_social, cc_habitual FROM contratistas WHERE estado='Activo' ORDER BY razon_social",
        conn,
    )
    contratistas = [
        {"id": int(r["id"]), "razon_social": r["razon_social"], "cc_habitual": r["cc_habitual"] or ""}
        for _, r in df.iterrows()
    ]
    sel = request.args.get("contratista_id") or (str(contratistas[0]["id"]) if contratistas else "")
    sel_item = next((c for c in contratistas if str(c["id"]) == sel), contratistas[0] if contratistas else None)
    return {
        "servicio_contratistas": contratistas,
        "servicio_sel_id": sel,
        "servicio_sel": sel_item,
        "centros_costo": demo.CENTROS_COSTO,
        "razones_sociales": demo.RAZONES_SOCIALES_COMPRAS,
        "hoy": demo.hoy.isoformat(),
        "sin_contratistas": not contratistas,
    }


def _contratistas_por_cc(demo, conn) -> dict:
    from erp_contratistas import fechas_consulta_contratistas_cc, listar_contratistas, query_imputaciones_contratistas_cc

    cuarteles = demo.CUARTELES_OFICIALES
    cc = request.args.get("cc") or (cuarteles[0] if cuarteles else "")
    if cc not in cuarteles:
        cc = cuarteles[0] if cuarteles else ""

    ct_rows = listar_contratistas(conn, solo_activos=False)
    ct_opts = {"": "Todos"}
    for cid, raz, _rut, _est in ct_rows:
        ct_opts[str(cid)] = str(raz)
    ct_id_raw = request.args.get("contratista", "")
    ct_id = int(ct_id_raw) if ct_id_raw.isdigit() else None

    cc_u = cc.upper()
    fi_def, ff_def = fechas_consulta_contratistas_cc(conn, cc_u)
    fi, ff = _fechas_con_reset_cc(cc_u, fi_def, ff_def, "rrhh_ct_por_cc")

    df = query_imputaciones_contratistas_cc(conn, cc.upper(), fi, ff, contratista_id=ct_id)
    rows = []
    total = 0.0
    for _, r in df.iterrows():
        monto = float(r.get("MONTO") or 0)
        total += monto
        rows.append(
            {
                "fecha": str(r.get("FECHA", ""))[:10],
                "contratista": r.get("CONTRATISTA", ""),
                "documento": r.get("DOCUMENTO", ""),
                "concepto": r.get("SERVICIO", r.get("CONCEPTO", "")),
                "monto": demo.f_peso(monto),
            }
        )
    pdf_url = None
    if not df.empty:
        blob = demo.generar_pdf_blob(df, f"CONTRATISTAS - {cc.upper()}", campo_suma_forzado="MONTO")
        if blob:
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, f"contratistas_{cc.lower()}.pdf"))
    return {
        "cuarteles": cuarteles,
        "cc_sel": cc,
        "contratistas_filtro": ct_opts,
        "contratista_sel": ct_id_raw,
        "por_cc_rows": rows,
        "por_cc_total": demo.f_peso(total),
        "por_cc_n": len(rows),
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_por_cc_url": pdf_url,
    }


def _contratistas_cuenta(demo, conn) -> dict:
    from erp_contratistas import (
        fechas_consulta_contratistas_cc,
        listar_contratistas,
        query_cuenta_corriente_contratista,
    )

    ct_rows = listar_contratistas(conn, solo_activos=True)
    if not ct_rows:
        return {"cta_vacia": True, "cta_rows": [], "contratistas_cta": {}}

    ct_map = {str(r[1]): int(r[0]) for r in ct_rows}
    ct_sel = request.args.get("contratista") or list(ct_map.keys())[0]
    if ct_sel not in ct_map:
        ct_sel = list(ct_map.keys())[0]

    cc_raw = request.args.get("cc_filtro", "")
    cc_u = cc_raw.upper() if cc_raw and cc_raw in demo.CUARTELES_OFICIALES else None

    hoy = hoy_demo(demo)
    if cc_u:
        fi_def, ff_def = fechas_consulta_contratistas_cc(conn, cc_u)
    else:
        fi_def, ff_def = hoy - timedelta(days=365), hoy
    ctx_key = f"{cc_raw or ''}|{cc_u or ''}"
    fi, ff = _fechas_con_reset_cc(ctx_key, fi_def, ff_def, "rrhh_ct_cuenta_cc")

    df, razon = query_cuenta_corriente_contratista(conn, ct_map[ct_sel], fi, ff, cc_u=cc_u)
    rows = []
    tot_debe = tot_haber = 0.0
    for _, r in df.iterrows():
        debe = float(r.get("DEBE") or 0)
        haber = float(r.get("HABER") or 0)
        tot_debe += debe
        tot_haber += haber
        rows.append(
            {
                "fecha": str(r.get("FECHA", ""))[:10],
                "tipo": r.get("TIPO", ""),
                "documento": r.get("DOCUMENTO", ""),
                "detalle": r.get("DETALLE", ""),
                "debe": demo.f_peso(debe) if debe else "",
                "haber": demo.f_peso(haber) if haber else "",
                "saldo": demo.f_peso(r.get("SALDO") or 0),
            }
        )
    saldo_final = float(df["SALDO"].iloc[-1]) if not df.empty else 0.0
    pdf_url = None
    if not df.empty:
        suf_cc = f"_{cc_u.lower().replace(' ', '_')}" if cc_u else ""
        titulo = (
            f"CTA CTE {str(razon or '').upper()} "
            f"({fi.strftime('%d-%m-%Y')} al {ff.strftime('%d-%m-%Y')})"
        )
        titulo += f" - CC {cc_u}" if cc_u else " - TODOS LOS CENTROS DE COSTOS"
        blob = demo.generar_pdf_blob(df, titulo, incluir_precios=False, orden_asc=True)
        if blob:
            pdf_url = url_for(
                "modules.pdf_download",
                token=store_pdf(blob, f"cta_cte_{ct_map[ct_sel]}{suf_cc}.pdf"),
            )
    return {
        "cta_vacia": False,
        "contratistas_cta": ct_map,
        "contratista_cta_sel": ct_sel,
        "cc_filtro_opts": demo.CUARTELES_OFICIALES,
        "cc_filtro_sel": cc_raw,
        "cta_rows": rows,
        "cta_razon": razon,
        "cta_tot_gen": demo.f_peso(tot_debe),
        "cta_tot_pag": demo.f_peso(tot_haber),
        "cta_saldo": demo.f_peso(saldo_final),
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_cta_url": pdf_url,
        "pdf_cta_rows": len(rows),
    }


def _remuneraciones(demo, conn) -> dict:
    h = demo.hora_chile()
    prov_m = demo._mes_rrhh_norm(request.args.get("mes") or h.strftime("%m"))
    try:
        prov_a = int(request.args.get("anio") or h.year)
    except ValueError:
        prov_a = h.year

    df_act = pd.read_sql_query("SELECT id, nombre FROM personal WHERE estado='Activo'", conn)
    trabajadores = [{"id": int(r["id"]), "nombre": r["nombre"]} for _, r in df_act.iterrows()]
    tid_sel = int(request.args.get("trabajador_id") or (trabajadores[0]["id"] if trabajadores else 0))
    ficha = conn.execute(
        """SELECT sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas, suple_fijo,
                  primera_cuota_mes, primera_cuota_anio
           FROM remuneraciones_fichas WHERE trabajador_id=?""",
        (tid_sel,),
    ).fetchone()
    info_prest = demo._info_prestamo_worker(conn, tid_sel) if tid_sel else {}

    q_prest = """SELECT p.nombre AS trabajador,
                        f.monto_prestamo AS prestamo_total,
                        f.cuotas_prestamo AS cuotas_pactadas,
                        COALESCE(f.cuotas_pagadas, 0) AS cuotas_pagadas,
                        CASE WHEN f.primera_cuota_mes IS NOT NULL AND f.primera_cuota_anio IS NOT NULL
                             THEN printf('%02d', CAST(f.primera_cuota_mes AS INTEGER)) || '/' || f.primera_cuota_anio
                             ELSE 'Inmediato' END AS primera_cuota,
                        COALESCE((SELECT SUM(descuento_prestamo) FROM remuneracion_mes WHERE trabajador_id = p.id), 0) AS total_descontado,
                        MAX(0, f.monto_prestamo - COALESCE((SELECT SUM(descuento_prestamo) FROM remuneracion_mes WHERE trabajador_id = p.id), 0)) AS saldo_pendiente
                 FROM personal p
                 JOIN remuneraciones_fichas f ON p.id = f.trabajador_id
                 WHERE p.estado='Activo' AND f.monto_prestamo > 0
                 ORDER BY p.nombre"""
    df_prest = pd.read_sql_query(q_prest, conn)
    prestamos = []
    for _, r in df_prest.iterrows():
        prestamos.append(
            {
                "trabajador": r["trabajador"],
                "prestamo_total": demo.f_peso(r["prestamo_total"]),
                "cuotas_pactadas": int(r["cuotas_pactadas"] or 0),
                "cuotas_pagadas": int(r["cuotas_pagadas"] or 0),
                "primera_cuota": r["primera_cuota"],
                "total_descontado": demo.f_peso(r["total_descontado"]),
                "saldo_pendiente": demo.f_peso(r["saldo_pendiente"]),
            }
        )

    q_prov = """SELECT p.id AS trabajador_id, p.nombre AS trabajador,
                       CASE WHEN r.trabajador_id IS NOT NULL THEN COALESCE(r.liquido_ganado, 0)
                            ELSE COALESCE(f.sueldo_pactado, 0) END AS liquido_ganado,
                       CASE WHEN r.trabajador_id IS NOT NULL THEN COALESCE(r.suple, 0)
                            ELSE COALESCE(f.suple_fijo, 0) END AS suple,
                       COALESCE(r.descuento_prestamo, 0) AS descuento_prestamo
                FROM personal p
                LEFT JOIN remuneraciones_fichas f ON p.id = f.trabajador_id
                LEFT JOIN remuneracion_mes r ON r.trabajador_id = p.id AND r.mes = ? AND r.anio = ?
                WHERE p.estado = 'Activo'
                ORDER BY p.nombre"""
    df_prov = pd.read_sql_query(q_prov, conn, params=(prov_m, prov_a)).fillna(0)
    planilla = []
    total_prov = 0.0
    for _, row in df_prov.iterrows():
        tid = int(row["trabajador_id"])
        desc = float(row["descuento_prestamo"] or 0)
        if desc <= 0:
            desc = float(demo._descuento_cuota_sugerida(conn, tid, prov_m, prov_a) or 0)
        liq = float(row["liquido_ganado"] or 0)
        sup = float(row["suple"] or 0)
        prov = max(0, liq - sup - desc)
        total_prov += prov
        planilla.append(
            {
                "trabajador_id": tid,
                "trabajador": row["trabajador"],
                "liquido_ganado": liq,
                "suple": sup,
                "descuento_prestamo": desc,
                "liquido_a_provisionar": prov,
                "liquido_fmt": demo.f_peso(liq),
                "suple_fmt": demo.f_peso(sup),
                "desc_fmt": demo.f_peso(desc),
                "prov_fmt": demo.f_peso(prov),
            }
        )

    primera_def = demo._primera_cuota_date_default(ficha).isoformat() if ficha else demo.hoy.isoformat()
    return {
        "meses": MESES,
        "mes_sel": prov_m,
        "anio_sel": prov_a,
        "trabajadores": trabajadores,
        "trabajador_sel": tid_sel,
        "ficha_sueldo": float(ficha[0] or 0) if ficha else 0,
        "ficha_suple": float(ficha[4] or 0) if ficha else 0,
        "info_prestamo": info_prest,
        "primera_cuota_def": primera_def,
        "prestamos_rows": prestamos,
        "planilla_rows": planilla,
        "total_provision": demo.f_peso(total_prov),
    }


def _liquidacion(demo, conn) -> dict:
    h = demo.hora_chile()
    df_act = pd.read_sql_query("SELECT id, nombre FROM personal WHERE estado='Activo'", conn)
    trabajadores = [{"id": int(r["id"]), "nombre": r["nombre"]} for _, r in df_act.iterrows()]
    tid = int(request.args.get("trabajador_id") or (trabajadores[0]["id"] if trabajadores else 0))
    mes = demo._mes_rrhh_norm(request.args.get("mes") or h.strftime("%m"))
    try:
        anio = int(request.args.get("anio") or h.year)
    except ValueError:
        anio = h.year

    existente = None
    if tid:
        row = conn.execute(
            """SELECT liquido, leyes_sociales FROM pagos_rrhh
               WHERE trabajador_id=? AND printf('%02d', CAST(mes AS INTEGER))=? AND anio=?""",
            (tid, mes, anio),
        ).fetchone()
        if row:
            existente = {"liquido": float(row[0] or 0), "leyes": float(row[1] or 0)}

    return {
        "meses": MESES,
        "liq_trabajadores": trabajadores,
        "liq_trabajador_sel": tid,
        "liq_mes": mes,
        "liq_anio": anio,
        "liq_existente": existente,
        "sin_trabajadores": not trabajadores,
    }


def _historial_pagos(demo, conn) -> dict:
    hoy = demo.hoy
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=120))
    ff = parse_date(request.args.get("hasta"), hoy)
    sub = demo._subquery_pagos_rrhh_canonicos()
    df = pd.read_sql_query(
        f"""SELECT p.nombre AS trabajador, h.mes AS mes, h.anio AS anio,
                   h.liquido AS liquido_pagado, h.leyes_sociales AS previred,
                   (h.liquido + h.leyes_sociales) AS total_pagado,
                   h.fecha_registro AS fecha_registro
            FROM ({sub}) h
            JOIN personal p ON h.trabajador_id = p.id
            WHERE h.fecha_registro BETWEEN ? AND ?
            ORDER BY h.anio DESC, CAST(h.mes AS INTEGER) DESC, p.nombre""",
        conn,
        params=(str(fi), str(ff)),
    )
    rows = []
    total = 0.0
    for _, r in df.iterrows():
        tot = float(r["total_pagado"] or 0)
        total += tot
        rows.append(
            {
                "trabajador": r["trabajador"],
                "mes": demo._mes_rrhh_norm(r["mes"]),
                "anio": int(r["anio"]),
                "liquido_pagado": demo.f_peso(r["liquido_pagado"]),
                "previred": demo.f_peso(r["previred"]),
                "total_pagado": demo.f_peso(tot),
                "fecha_registro": str(r["fecha_registro"] or "")[:10],
            }
        )
    pdf_url = None
    if not df.empty:
        show = df.rename(
            columns={
                "trabajador": "TRABAJADOR",
                "mes": "MES",
                "anio": "AÑO",
                "liquido_pagado": "LIQUIDO_PAGADO",
                "previred": "PREVIRED",
                "total_pagado": "TOTAL_PAGADO",
                "fecha_registro": "FECHA_REGISTRO",
            }
        )
        blob = demo.generar_pdf_blob(show, "HISTORIAL GENERAL DE REMUNERACIONES", campo_suma_forzado="TOTAL_PAGADO")
        if blob:
            pdf_url = url_for("modules.pdf_download", token=store_pdf(blob, "historial_pagos_rrhh.pdf"))
    return {
        "historial_rows": rows,
        "historial_total": demo.f_peso(total),
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "pdf_historial_url": pdf_url,
    }


def gather_rrhh(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    sec = request.args.get("sec", "personal")
    if sec not in {k for k, _ in SECCIONES}:
        sec = "personal"

    conn = demo.conectar_db()
    try:
        ctx: dict = {"secciones": SECCIONES, "sec_activa": sec}
        if sec == "personal":
            ctx.update(_personal(demo, conn))
        elif sec == "contratistas":
            sub = request.args.get("sub", "maestro")
            if sub not in {k for k, _ in CONTRATISTAS_SEC}:
                sub = "maestro"
            ctx["contratistas_sec"] = CONTRATISTAS_SEC
            ctx["sub_activa"] = sub
            if sub == "maestro":
                ctx.update(_contratistas_maestro(demo, conn))
            elif sub == "servicio":
                ctx.update(_contratistas_servicio(demo, conn))
            elif sub == "por_cc":
                ctx.update(_contratistas_por_cc(demo, conn))
            elif sub == "cuenta":
                ctx.update(_contratistas_cuenta(demo, conn))
        elif sec == "remuneraciones":
            ctx.update(_remuneraciones(demo, conn))
        elif sec == "liquidacion":
            ctx.update(_liquidacion(demo, conn))
        elif sec == "historial":
            ctx.update(_historial_pagos(demo, conn))
        return ctx
    finally:
        conn.close()


def _post_crear_personal(demo, conn) -> dict:
    from erp_rut import validar_rut_campo

    migrar_personal_salida_petroleo(conn)
    nom = (request.form.get("nombre") or "").strip()
    rut_raw = request.form.get("rut") or ""
    cargo = (request.form.get("cargo") or "").strip()
    fecha = request.form.get("fecha_contrato") or str(demo.hoy)
    auth_pet = 1 if request.form.get("autorizado_salida_petroleo") == "1" else 0
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=True)
    if not nom:
        return {"ok": False, "msg": "Ingrese el nombre del trabajador."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    conn.execute(
        """INSERT INTO personal (nombre, rut, cargo, fecha_contrato, autorizado_salida_petroleo)
           VALUES (?,?,?,?,?)""",
        (nom, rut_fmt, cargo, fecha, auth_pet),
    )
    conn.commit()
    demo.registrar_accion("RRHH", nom)
    return {"ok": True, "msg": f"Trabajador {nom} registrado."}


def _post_editar_personal(demo, conn) -> dict:
    from erp_rut import validar_rut_campo

    migrar_personal_salida_petroleo(conn)
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    pid = int(request.form.get("personal_id") or 0)
    nom = (request.form.get("nombre") or "").strip()
    rut_raw = request.form.get("rut") or ""
    cargo = (request.form.get("cargo") or "").strip()
    fecha = request.form.get("fecha_contrato") or str(demo.hoy)
    auth_pet = 1 if request.form.get("autorizado_salida_petroleo") == "1" else 0
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(rut_raw, obligatorio=True)
    if not pid or not nom:
        return {"ok": False, "msg": "Datos incompletos."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    conn.execute(
        """UPDATE personal SET nombre=?, rut=?, cargo=?, fecha_contrato=?,
           autorizado_salida_petroleo=? WHERE id=?""",
        (nom, rut_fmt, cargo, fecha, auth_pet, pid),
    )
    conn.commit()
    demo.registrar_accion("UPDATE RRHH", nom)
    return {"ok": True, "msg": "Ficha actualizada."}


def _post_eliminar_personal(demo, conn) -> dict:
    if not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Clave maestra incorrecta."}
    pid = int(request.form.get("personal_id") or 0)
    row = conn.execute("SELECT nombre FROM personal WHERE id=?", (pid,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Trabajador no encontrado."}
    conn.execute("DELETE FROM personal WHERE id=?", (pid,))
    conn.commit()
    demo.registrar_accion("DELETE RRHH", row[0])
    return {"ok": True, "msg": "Trabajador eliminado."}


def _post_crear_contratista(demo, conn) -> dict:
    from erp_contratistas import excluir_contratista_de_maestra_proveedores
    from erp_rut import validar_rut_campo

    raz = (request.form.get("razon_social") or "").strip()
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(request.form.get("rut") or "", obligatorio=False)
    if not raz:
        return {"ok": False, "msg": "La razón social es obligatoria."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    cc = request.form.get("cc_habitual") or ""
    cc_h = None if not cc or cc == "—" else cc
    conn.execute(
        """INSERT INTO contratistas
           (rut, razon_social, rubro, contacto, cc_habitual, estado, notas, email, mail_pago, celular, whatsapp_pago)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rut_fmt,
            raz,
            (request.form.get("rubro") or "").strip(),
            (request.form.get("contacto") or "").strip(),
            cc_h,
            "Activo",
            (request.form.get("notas") or "").strip(),
            (request.form.get("email") or "").strip(),
            1 if request.form.get("mail_pago") == "1" else 0,
            (request.form.get("celular") or "").strip(),
            1 if request.form.get("whatsapp_pago") == "1" else 0,
        ),
    )
    excluir_contratista_de_maestra_proveedores(conn, raz)
    conn.commit()
    demo.registrar_accion("RRHH CONTRATISTA", raz)
    return {"ok": True, "msg": f"Contratista {raz} registrado."}


def _post_editar_contratista(demo, conn) -> dict:
    from erp_contratistas import excluir_contratista_de_maestra_proveedores
    from erp_rut import validar_rut_campo

    if not demo.es_admin() or not _check_master(demo, request.form.get("clave_maestra")):
        return {"ok": False, "msg": "Requiere perfil admin y clave maestra."}
    cid = int(request.form.get("contratista_id") or 0)
    raz = (request.form.get("razon_social") or "").strip()
    ok_rut, msg_rut, rut_fmt = validar_rut_campo(request.form.get("rut") or "", obligatorio=False)
    if not cid or not raz:
        return {"ok": False, "msg": "Datos incompletos."}
    if not ok_rut:
        return {"ok": False, "msg": msg_rut}
    cc = request.form.get("cc_habitual") or ""
    cc_h = None if not cc or cc == "—" else cc
    conn.execute(
        """UPDATE contratistas SET rut=?, razon_social=?, rubro=?, contacto=?, cc_habitual=?, estado=?, notas=?,
           email=?, mail_pago=?, celular=?, whatsapp_pago=? WHERE id=?""",
        (
            rut_fmt,
            raz,
            (request.form.get("rubro") or "").strip(),
            (request.form.get("contacto") or "").strip(),
            cc_h,
            request.form.get("estado") or "Activo",
            (request.form.get("notas") or "").strip(),
            (request.form.get("email") or "").strip(),
            1 if request.form.get("mail_pago") == "1" else 0,
            (request.form.get("celular") or "").strip(),
            1 if request.form.get("whatsapp_pago") == "1" else 0,
            cid,
        ),
    )
    excluir_contratista_de_maestra_proveedores(conn, raz)
    conn.commit()
    return {"ok": True, "msg": "Contratista actualizado."}


def _post_registrar_servicio(demo, conn) -> dict:
    cid = int(request.form.get("contratista_id") or 0)
    sin_doc = request.form.get("sin_doc") == "1"
    nro = (request.form.get("nro_doc") or "").strip()
    fecha = request.form.get("fecha") or str(demo.hoy)
    fv = request.form.get("fecha_vence") or str(demo.hoy)
    concepto = (request.form.get("concepto") or "").strip()
    razon = request.form.get("razon_social") or demo.RAZONES_SOCIALES_COMPRAS[0]
    iva_bruto = request.form.get("iva_bruto") == "1"
    try:
        monto = float(request.form.get("monto") or 0)
    except ValueError:
        return {"ok": False, "msg": "Monto inválido."}
    selcc = [c for c in demo.CENTROS_COSTO if request.form.get(f"cc_{c}") == "1"]

    row = conn.execute("SELECT razon_social FROM contratistas WHERE id=?", (cid,)).fetchone()
    if not row:
        return {"ok": False, "msg": "Contratista no encontrado."}
    if not concepto:
        return {"ok": False, "msg": "Ingrese el concepto del servicio."}
    if monto <= 0:
        return {"ok": False, "msg": "El monto debe ser superior a $0."}
    if not selcc:
        return {"ok": False, "msg": "Seleccione al menos un centro de costo."}

    ndoc = demo._siguiente_folio_contratista(conn, fecha) if sin_doc else nro
    if not ndoc:
        return {"ok": False, "msg": "N° documento obligatorio."}

    ok, err = demo._registrar_servicio_contratista(
        conn, cid, row[0], ndoc, fecha, fv, monto, concepto, selcc, razon, imputar_bruto=iva_bruto,
    )
    if not ok:
        return {"ok": False, "msg": err or "No se pudo registrar."}
    conn.commit()
    demo.registrar_accion("RRHH CONTRATISTA SERVICIO", f"{row[0]} {ndoc}")
    return {"ok": True, "msg": f"Servicio registrado ({ndoc})."}


def _post_guardar_ficha(demo, conn) -> dict:
    tid = int(request.form.get("trabajador_id") or 0)
    mes = demo._mes_rrhh_norm(request.form.get("mes") or "")
    anio = int(request.form.get("anio") or demo.hora_chile().year)
    try:
        sueldo = float(request.form.get("sueldo") or 0)
        suple = float(request.form.get("suple") or 0)
    except ValueError:
        return {"ok": False, "msg": "Valores inválidos."}
    ficha = conn.execute(
        "SELECT monto_prestamo, cuotas_prestamo, cuotas_pagadas, primera_cuota_mes, primera_cuota_anio FROM remuneraciones_fichas WHERE trabajador_id=?",
        (tid,),
    ).fetchone()
    m_prest = float(ficha[0] or 0) if ficha else 0
    c_prest = int(ficha[1] or 0) if ficha else 0
    c_pag = int(ficha[2] or 0) if ficha else 0
    pc_m = ficha[3] if ficha else None
    pc_a = ficha[4] if ficha else None
    conn.execute(
        """INSERT OR REPLACE INTO remuneraciones_fichas
           (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas, suple_fijo, primera_cuota_mes, primera_cuota_anio)
           VALUES (?,?,?,?,?,?,?,?)""",
        (tid, sueldo, m_prest, c_prest, c_pag, suple, pc_m, pc_a),
    )
    desc = demo._descuento_cuota_sugerida(conn, tid, mes, anio)
    ok, err = demo._guardar_remuneracion_mes(conn, tid, mes, anio, sueldo, suple, desc)
    if not ok:
        conn.commit()
        return {"ok": False, "msg": err or "Error al guardar planilla."}
    conn.commit()
    demo.registrar_accion("RRHH FICHA", f"planilla {mes}/{anio}")
    return {"ok": True, "msg": f"Sueldo/suple guardados en planilla {mes}/{anio}."}


def _post_registrar_prestamo(demo, conn) -> dict:
    tid = int(request.form.get("trabajador_id") or 0)
    try:
        monto = float(request.form.get("monto_prestamo") or 0)
        cuotas = int(request.form.get("cuotas") or 0)
    except ValueError:
        return {"ok": False, "msg": "Valores inválidos."}
    if monto <= 0 or cuotas <= 0:
        return {"ok": False, "msg": "Monto y cuotas deben ser mayores a cero."}
    primera = request.form.get("primera_cuota") or str(demo.hoy)
    pc_m, pc_a = demo._mes_anio_desde_fecha(parse_date(primera, demo.hoy))
    ficha = conn.execute(
        "SELECT sueldo_pactado, suple_fijo FROM remuneraciones_fichas WHERE trabajador_id=?",
        (tid,),
    ).fetchone()
    sueldo = float(ficha[0] or 0) if ficha else 0
    suple = float(ficha[1] or 0) if ficha else 0
    conn.execute(
        """INSERT OR REPLACE INTO remuneraciones_fichas
           (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, cuotas_pagadas, suple_fijo, primera_cuota_mes, primera_cuota_anio)
           VALUES (?,?,?,?,0,?,?,?)""",
        (tid, sueldo, monto, cuotas, suple, pc_m, pc_a),
    )
    conn.commit()
    demo.registrar_accion("RRHH PRESTAMO NUEVO", str(tid))
    return {"ok": True, "msg": "Préstamo registrado."}


def _post_guardar_planilla(demo, conn) -> dict:
    mes = demo._mes_rrhh_norm(request.form.get("mes") or "")
    anio = int(request.form.get("anio") or demo.hora_chile().year)
    errores = []
    for key in request.form:
        if not key.startswith("liq_"):
            continue
        tid = int(key.replace("liq_", ""))
        try:
            liq = float(request.form.get(f"liq_{tid}") or 0)
            sup = float(request.form.get(f"sup_{tid}") or 0)
            desc = float(request.form.get(f"desc_{tid}") or 0)
        except ValueError:
            errores.append(f"ID {tid}: valores inválidos")
            continue
        if desc <= 0:
            desc = demo._descuento_cuota_sugerida(conn, tid, mes, anio)
        ok, err = demo._guardar_remuneracion_mes(conn, tid, mes, anio, liq, sup, desc)
        if not ok:
            errores.append(err or f"Error trabajador {tid}")
    if errores:
        return {"ok": False, "msg": "; ".join(errores[:3])}
    conn.commit()
    demo.registrar_accion("RRHH REMUNERACION MES", f"{mes}/{anio}")
    return {"ok": True, "msg": f"Planilla {mes}/{anio} guardada."}


def _post_liquidacion(demo, conn) -> dict:
    tid = int(request.form.get("trabajador_id") or 0)
    mes = demo._mes_rrhh_norm(request.form.get("mes") or "")
    anio = int(request.form.get("anio") or demo.hora_chile().year)
    licencia = request.form.get("licencia") == "1"
    try:
        liq = float(request.form.get("liquido") or 0)
        ley = float(request.form.get("leyes") or 0)
    except ValueError:
        return {"ok": False, "msg": "Montos inválidos."}
    ok, err = demo._upsert_pago_rrhh(conn, tid, mes, anio, liq, ley, licencia)
    if not ok:
        return {"ok": False, "msg": err or "Error al guardar."}
    tot = 0 if licencia else liq + ley
    demo._imputar_costos_rrhh(conn, tid, mes, anio, tot)
    conn.commit()
    demo.registrar_accion("RRHH PAGO NETO", f"{tid} {mes}/{anio}")
    return {"ok": True, "msg": f"Liquidación guardada ({mes}/{anio})."}


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        sec = request.form.get("sec") or request.args.get("sec", "personal")
        sub = request.form.get("sub") or request.args.get("sub", "")
        conn = demo.conectar_db()
        try:
            handlers = {
                "crear_personal": _post_crear_personal,
                "editar_personal": _post_editar_personal,
                "eliminar_personal": _post_eliminar_personal,
                "crear_contratista": _post_crear_contratista,
                "editar_contratista": _post_editar_contratista,
                "registrar_servicio": _post_registrar_servicio,
                "guardar_ficha": _post_guardar_ficha,
                "registrar_prestamo": _post_registrar_prestamo,
                "guardar_planilla": _post_guardar_planilla,
                "liquidacion": _post_liquidacion,
            }
            fn = handlers.get(action)
            if fn:
                result = fn(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                extra = {"sec": sec}
                if sub:
                    extra["sub"] = sub
                if action in ("editar_personal", "eliminar_personal"):
                    extra["edit_id"] = request.form.get("personal_id", "")
                if action == "editar_contratista":
                    extra["edit_id"] = request.form.get("contratista_id", "")
                if action == "registrar_servicio":
                    extra["contratista_id"] = request.form.get("contratista_id", "")
                if action in ("guardar_ficha", "registrar_prestamo", "guardar_planilla", "liquidacion"):
                    extra["mes"] = request.form.get("mes", "")
                    extra["anio"] = request.form.get("anio", "")
                    extra["trabajador_id"] = request.form.get("trabajador_id", "")
                return _redirect_rrhh(**extra)
        finally:
            conn.close()

    ctx = gather_rrhh(user_email, user_rol)
    return render_template(
        "modules/rrhh.html",
        page_title="RRHH",
        active_key="RRHH",
        title="👥 Recursos Humanos",
        **ctx,
    )
