from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("faenas", "Faenas"),
    ("mantencion", "Mantención"),
    ("historial", "Historial"),
]

_ETIQUETAS_CERRADAS = {"CERRADO", "CONFORME"}


def _select_maquinaria(conn, tipos=None) -> list[tuple[str, str]]:
    from erp_maquinaria import etiqueta_maquinaria, listar_maquinaria

    items = listar_maquinaria(conn, solo_activos=True, tipos=tipos)
    if not items and tipos:
        items = listar_maquinaria(conn, solo_activos=True)
    return [(m["codigo"], etiqueta_maquinaria(m["codigo"], m["nombre"])) for m in items]


def _codigo_desde_celda(valor: str) -> str:
    txt = str(valor or "").strip()
    if " — " in txt:
        return txt.split(" — ", 1)[0].strip().upper()
    return txt.upper()


def _row_class_historial(maquinaria: str, etiqueta: str, codigos_rep: set[str]) -> str:
    from erp_maquinaria import etiqueta_maquinaria_cerrada

    cod = _codigo_desde_celda(maquinaria)
    etiq = str(etiqueta or "").strip().upper()
    if cod in codigos_rep:
        if not etiqueta_maquinaria_cerrada(etiq):
            return "table-warning fw-semibold"
        return "table-light"
    if not etiqueta_maquinaria_cerrada(etiq):
        return "table-danger"
    return ""


def _faenas(demo, conn) -> dict:
    from erp_maquinaria import (
        TIPOS_MAQUINARIA,
        TIPOS_MAQUINARIA_TRACTOR,
        _cargar_df_asignacion_faena,
        _html_ticket_faena_operador,
        enriquecer_columna_maquinaria,
        migrar_asignacion_faena_diaria,
        texto_maquinaria_para_display,
    )

    migrar_asignacion_faena_diaria(conn)
    hoy = hoy_demo(demo)
    sub = request.args.get("sub", "registrar")
    if sub not in ("registrar", "ticket"):
        sub = "registrar"

    fi = parse_date(request.args.get("faena_desde"), hoy)
    ff = parse_date(request.args.get("faena_hasta"), hoy)
    df = _cargar_df_asignacion_faena(conn, fi, ff)

    faena_rows = []
    pdf_url = None
    if not df.empty:
        df_show = df.drop(columns=["id"]).copy()
        df_show = enriquecer_columna_maquinaria(conn, df_show, "TRACTOR")
        df_show = enriquecer_columna_maquinaria(conn, df_show, "EQUIPO")
        faena_rows = df_show.fillna("").to_dict(orient="records")
        blob = demo.generar_pdf_blob(
            df_show,
            f"ASIGNACIÓN FAENAS ({fi} a {ff})",
            incluir_precios=False,
        )
        if blob:
            token = store_pdf(blob, "asignacion_faenas.pdf")
            pdf_url = url_for("modules.pdf_download", token=token)

    ticket_html = None
    ticket_opts = []
    if sub == "ticket":
        f_ticket = parse_date(request.args.get("ticket_dia"), hoy)
        df_t = _cargar_df_asignacion_faena(conn, f_ticket, f_ticket)
        for _, row in df_t.iterrows():
            ticket_opts.append(
                {
                    "id": int(row["id"]),
                    "label": f"{row['FECHA']} · {row['CUARTEL']} · {row['OPERADOR']} — {row['FAENA']}",
                }
            )
        sel_id = request.args.get("ticket_id")
        if sel_id and sel_id.isdigit():
            tid = int(sel_id)
        elif ticket_opts:
            tid = ticket_opts[0]["id"]
        else:
            tid = None

        if tid is not None and not df_t.empty and tid in df_t["id"].values:
            row = df_t[df_t["id"] == tid].iloc[0]
            try:
                f_show = pd.to_datetime(row["FECHA"]).strftime("%d-%m-%Y")
            except Exception:
                f_show = str(row["FECHA"])
            tr_raw = str(row.get("TRACTOR", "") or "").strip()
            ticket_html = _html_ticket_faena_operador(
                fecha=f_show,
                cuartel=row["CUARTEL"],
                operador=row["OPERADOR"],
                faena=row["FAENA"],
                equipo_txt=texto_maquinaria_para_display(conn, row.get("EQUIPO", "")),
                tractor_txt=texto_maquinaria_para_display(conn, tr_raw) if tr_raw else "",
                notas=row.get("NOTAS", ""),
                ticket_id=tid,
                nombre_erp="ERP Demo Agrícola",
            )

    return {
        "faena_sub": sub,
        "faena_rows": faena_rows,
        "faena_desde": fi.isoformat(),
        "faena_hasta": ff.isoformat(),
        "pdf_faenas_url": pdf_url,
        "cuarteles": demo.CENTROS_COSTO,
        "equipos_opts": _select_maquinaria(conn, tipos=TIPOS_MAQUINARIA),
        "tractores_opts": _select_maquinaria(conn, tipos=TIPOS_MAQUINARIA_TRACTOR),
        "form_fecha": hoy.isoformat(),
        "ticket_dia": parse_date(request.args.get("ticket_dia"), hoy).isoformat(),
        "ticket_opts": ticket_opts,
        "ticket_sel": request.args.get("ticket_id", ""),
        "ticket_html": ticket_html,
    }


def _historial(demo, conn) -> dict:
    from erp_maquinaria import (
        ESTADOS_CASO_MAQ,
        _codigos_maquinaria_en_reparacion,
        listar_casos_abiertos_maquinaria,
        listar_observaciones_caso,
        migrar_seguimiento_caso_maquinaria,
        normalizar_estado_caso_maq,
        opciones_filtro_maquinaria,
    )

    hoy = hoy_demo(demo)
    fi = parse_date(request.args.get("desde"), hoy - timedelta(days=180))
    ff = parse_date(request.args.get("hasta"), hoy)
    filtro_maq = request.args.get("maquina", "TODAS")
    edit_cod = (request.args.get("edit") or "").strip()

    migrar_seguimiento_caso_maquinaria(conn)

    sql = """SELECT b.cod_registro AS cod_unico, b.fecha_evento AS fecha,
                    COALESCE(m.codigo || ' — ' || m.nombre, b.id_maquinaria) AS maquinaria,
                    b.tipo_evento AS tipo_evento, b.detalle_mantenimiento AS descripcion,
                    b.encargado_taller AS encargado, b.responsable_interno AS responsable,
                    b.etiqueta_ingreso AS etiqueta,
                    COALESCE(b.info_post, '') AS info_post
             FROM bitacora_maquinaria b
             LEFT JOIN maestra_maquinaria m ON UPPER(TRIM(m.codigo)) = UPPER(TRIM(b.id_maquinaria))
             WHERE b.fecha_evento BETWEEN ? AND ?"""
    params: list = [str(fi), str(ff)]
    if filtro_maq and filtro_maq != "TODAS":
        sql += " AND UPPER(TRIM(b.id_maquinaria)) = ?"
        params.append(filtro_maq.upper())
    sql += " ORDER BY b.id DESC"

    df = pd.read_sql_query(sql, conn, params=params)
    codigos_rep = _codigos_maquinaria_en_reparacion(conn)

    rows = []
    for _, r in df.iterrows():
        etiq = normalizar_estado_caso_maq(r["etiqueta"])
        rows.append(
            {
                "cod_unico": r["cod_unico"],
                "fecha": str(r["fecha"])[:10],
                "maquinaria": r["maquinaria"],
                "tipo_evento": r["tipo_evento"],
                "descripcion": r["descripcion"],
                "encargado": r["encargado"],
                "responsable": r["responsable"],
                "etiqueta": etiq,
                "info_post": str(r["info_post"] or ""),
                "es_cerrado": etiq in {"Cerrado conforme", "Cerrado desconforme"},
                "row_class": _row_class_historial(r["maquinaria"], etiq, codigos_rep),
            }
        )

    pdf_url = None
    if not df.empty:
        df_pdf = df.rename(
            columns={
                "cod_unico": "N° ÚNICO",
                "fecha": "FECHA",
                "maquinaria": "MAQUINARIA",
                "tipo_evento": "TIPO EVENTO",
                "descripcion": "DESCRIPCIÓN",
                "encargado": "ENCARGADO TALLER",
                "responsable": "RESPONSABLE",
                "etiqueta": "ESTADO",
                "info_post": "ÚLTIMA OBS.",
            }
        )
        blob = demo.generar_pdf_blob(
            df_pdf,
            f"REPORTE DE MANTENCIONES ({fi} a {ff})",
            incluir_precios=False,
        )
        if blob:
            token = store_pdf(blob, "bitacora_maquinaria.pdf")
            pdf_url = url_for("modules.pdf_download", token=token)

    casos = listar_casos_abiertos_maquinaria(conn)
    casos_rows = [
        {
            "cod_registro": c["cod_registro"],
            "label": f"{c['cod_registro']} — {c['codigo']} ({c['nombre']}) — {c['etiqueta']}",
            "etiqueta": c["etiqueta"],
        }
        for c in casos
    ]

    filtro_opts = [("TODAS", "TODAS")] + list(opciones_filtro_maquinaria(conn))

    edit_row = next((r for r in rows if r["cod_unico"] == edit_cod), None)
    if edit_row:
        edit_row = dict(edit_row)
        edit_row["observaciones"] = listar_observaciones_caso(conn, edit_row["cod_unico"])

    return {
        "historial_rows": rows,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "filtro_maquina": filtro_maq,
        "filtro_maquinas": filtro_opts,
        "pdf_historial_url": pdf_url,
        "casos_abiertos": casos_rows,
        "edit_evento": edit_row,
        "estados_caso": list(ESTADOS_CASO_MAQ),
    }


def _procesar_faena(demo, conn) -> dict:
    from erp_maquinaria import migrar_asignacion_faena_diaria

    migrar_asignacion_faena_diaria(conn)
    f_asig = parse_date(request.form.get("fecha"), hoy_demo(demo))
    cc = (request.form.get("cuartel") or "").upper()
    operador = (request.form.get("operador") or "").strip()
    detalle = (request.form.get("detalle") or "").strip()
    equipo = (request.form.get("equipo") or "").strip()
    tractor = (request.form.get("tractor") or "").strip()

    if cc not in demo.CENTROS_COSTO:
        return {"ok": False, "msg": "Cuartel inválido."}
    if not equipo:
        return {"ok": False, "msg": "Seleccione el equipo principal desde la maestra."}
    if not operador:
        return {"ok": False, "msg": "Ingrese operador o responsable."}
    if not detalle:
        return {"ok": False, "msg": "Indique la labor o detalle de la faena."}

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO asignacion_faena_diaria
           (fecha, centro_costo, codigo_tractor, codigo_equipo, operador, detalle_faena, notas, fecha_registro)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            str(f_asig),
            cc,
            tractor,
            equipo,
            operador,
            detalle,
            (request.form.get("notas") or "").strip(),
            str(hoy_demo(demo)),
        ),
    )
    conn.commit()
    tid = int(cur.lastrowid)
    demo.registrar_accion(
        "MAQ FAENA",
        f"{f_asig} {cc} {equipo}" + (f" + {tractor}" if tractor else ""),
    )
    return {
        "ok": True,
        "msg": "Asignación guardada. Abra Ticket operador para el pantallazo.",
        "ticket_id": tid,
    }


def _procesar_mantencion(demo, conn) -> dict:
    cod_maquina = (request.form.get("maquinaria") or "").strip()
    tipo_ev = request.form.get("tipo_evento") or demo.TIPOS_EVENTO_MAQ[0]
    f_evento = parse_date(request.form.get("fecha"), hoy_demo(demo))
    encargado = (request.form.get("encargado") or "").strip()
    responsable = (request.form.get("responsable") or "").strip()
    etiqueta = request.form.get("etiqueta") or demo.ETIQUETAS_MAQ[0]
    detalle = (request.form.get("detalle") or "").strip()

    if not cod_maquina or not detalle or not responsable:
        return {"ok": False, "msg": "Seleccione maquinaria y complete los campos obligatorios."}

    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id) FROM bitacora_maquinaria")
    res_max = cursor.fetchone()[0]
    prox_id = (int(res_max) + 1) if res_max else 1
    cod_unico = f"MANT-{prox_id:05d}"

    conn.execute(
        """INSERT INTO bitacora_maquinaria
           (cod_registro, id_maquinaria, tipo_evento, detalle_mantenimiento, encargado_taller,
            responsable_interno, fecha_evento, etiqueta_ingreso)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cod_unico, cod_maquina, tipo_ev, detalle, encargado, responsable, str(f_evento), etiqueta),
    )
    conn.commit()
    demo.registrar_accion("MAQUINARIA", f"Registro {cod_unico} - {cod_maquina}")
    return {"ok": True, "msg": f"Evento guardado con éxito bajo el código: {cod_unico}"}



def _procesar_editar_evento(demo, conn) -> dict:
    from flask import g, session

    from erp_maquinaria import actualizar_caso_maquinaria, migrar_seguimiento_caso_maquinaria

    migrar_seguimiento_caso_maquinaria(conn)
    cod = (request.form.get("cod_registro") or "").strip()
    estado = (request.form.get("estado") or "").strip()
    observacion = (request.form.get("observacion") or "").strip()
    usuario = ""
    if getattr(g, "user", None):
        usuario = g.user.get("email") or ""
    usuario = usuario or session.get("email") or ""
    ok, msg = actualizar_caso_maquinaria(
        conn,
        cod,
        estado=estado,
        observacion=observacion,
        usuario=str(usuario or ""),
    )
    if ok:
        demo.registrar_accion("MAQUINARIA SEGUIMIENTO", f"{cod} → {estado}: {observacion[:80]}")
    return {"ok": ok, "msg": msg}


def _procesar_cerrar_caso(demo, conn) -> dict:
    from erp_maquinaria import (
        actualizar_caso_maquinaria,
        etiqueta_maquinaria_cerrada,
        migrar_seguimiento_caso_maquinaria,
        normalizar_estado_caso_maq,
    )

    migrar_seguimiento_caso_maquinaria(conn)
    cod = (request.form.get("cod_registro") or "").strip()
    estado = normalizar_estado_caso_maq(request.form.get("estado") or "Cerrado conforme")
    observacion = (request.form.get("observacion") or "").strip()
    if not cod:
        return {"ok": False, "msg": "Seleccione un caso abierto."}
    if not observacion:
        if etiqueta_maquinaria_cerrada(estado):
            if estado == "Cerrado desconforme":
                observacion = "Caso cerrado desconforme."
            else:
                observacion = "Caso cerrado conforme — equipo vuelve a operación."
        else:
            return {"ok": False, "msg": "Anote una observación para el cambio de estado."}
    ok, msg = actualizar_caso_maquinaria(conn, cod, estado=estado, observacion=observacion)
    if ok:
        demo.registrar_accion("MAQUINARIA SEGUIMIENTO", f"{cod} → {estado}")
    return {"ok": ok, "msg": msg}


def gather_maquinaria(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    sec = request.args.get("sec", "faenas")
    if sec not in {k for k, _ in SECCIONES}:
        sec = "faenas"

    conn = demo.conectar_db()
    try:
        ctx: dict = {
            "secciones": SECCIONES,
            "sec_activa": sec,
            "tipos_evento": demo.TIPOS_EVENTO_MAQ,
            "etiquetas_maq": demo.ETIQUETAS_MAQ,
            "maquinaria_opts": _select_maquinaria(conn),
        }
        if sec == "faenas":
            ctx.update(_faenas(demo, conn))
        elif sec == "historial":
            ctx.update(_historial(demo, conn))
        elif sec == "mantencion":
            ctx["form_fecha"] = hoy_demo(demo).isoformat()
        return ctx
    finally:
        conn.close()


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        if demo.es_solo_lectura():
            flash("Modo solo lectura: no puede registrar ni modificar datos.", "warning")
            return redirect_module("maquinaria", sec=request.form.get("sec") or request.args.get("sec") or "faenas")
        action = request.form.get("action", "")
        conn = demo.conectar_db()
        try:
            if action == "faena":
                result = _procesar_faena(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                if result.get("ok"):
                    return redirect_module(
                        "maquinaria",
                        sec="faenas",
                        sub="ticket",
                        ticket_id=str(result["ticket_id"]),
                        ticket_dia=request.form.get("fecha", ""),
                    )
            elif action == "mantencion":
                result = _procesar_mantencion(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("maquinaria", sec="mantencion")
            elif action == "cerrar_caso":
                result = _procesar_cerrar_caso(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module("maquinaria", sec="historial")
            elif action == "editar_evento":
                result = _procesar_editar_evento(demo, conn)
                flash(result["msg"], "success" if result["ok"] else "danger")
                return redirect_module(
                    "maquinaria",
                    sec="historial",
                    maquina=request.form.get("maquina") or "TODAS",
                    desde=request.form.get("desde") or "",
                    hasta=request.form.get("hasta") or "",
                )
        finally:
            conn.close()

    ctx = gather_maquinaria(user_email, user_rol)
    return render_template(
        "modules/maquinaria.html",
        page_title="Maquinaria",
        active_key="Maquinaria",
        title="🚜 Maquinaria",
        **ctx,
    )
