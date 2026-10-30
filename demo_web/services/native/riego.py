from __future__ import annotations

from io import BytesIO

from flask import flash, render_template, request, send_file, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import redirect_module
from demo_web.services.native._helpers import hoy_demo, parse_date
from demo_web.services.tenant_scope import is_concepcion_tenant

SECCIONES = [
    ("historial", "📊 HISTORIAL"),
    ("manual", "✏️ REGISTRO MANUAL"),
    ("bitacora", "🔗 LINK RIEGO"),
]
SECCIONES_LC = [
    ("hoy", "Hoy"),
    ("regar", "Regar"),
    ("historial", "Historial"),
    ("armado", "Armado"),
]
REGAR_SUB = (
    ("ahora", "Ahora"),
    ("programar", "Programar"),
)
ARMADO_SUB = (
    ("sectores", "Sectores"),
    ("enlaces", "Enlaces"),
    ("parametros", "Parámetros"),
    ("manual", "A mano"),
)


def _canon_lc(sec: str, sub: str) -> tuple[str, str]:
    """La Concepción: las URLs viejas abren la pantalla nueva. El resto cae en Historial."""
    sec = (sec or "").strip()
    sub = (sub or "").strip()
    if sec == "hydra_config" or (sec == "hydra" and sub == "config"):
        return "armado", "sectores"
    if sec in ("hydra", "hydra_riego"):
        return "hoy", ""
    if sec == "manual":
        return "armado", "manual"
    if sec == "bitacora":
        return "hoy", ""
    if sec == "regar":
        if sub not in {k for k, _ in REGAR_SUB}:
            sub = "ahora"
        return "regar", sub
    if sec == "armado":
        if sub not in {k for k, _ in ARMADO_SUB}:
            sub = "sectores"
        return "armado", sub
    if sec == "hoy":
        return "hoy", ""
    if sec == "historial":
        return "historial", ""
    return "historial", ""


def _canon_post_hydra(sec: str, sub: str) -> tuple[str, str]:
    """Un POST de riego con el sec viejo «manual» vuelve a Hoy."""
    if (sec or "").strip() == "manual":
        return "hoy", ""
    return _canon_lc(sec or "hydra", sub)


def _volver(sec: str, sub: str = ""):
    return redirect_module("riego", sec=sec, sub=sub)


def _volver_historial():
    """Vuelve al historial con el filtro de la pantalla, sin repetir el PDF."""
    return redirect_module(
        "riego",
        sec="historial",
        sub="",
        pdf="",
        desde=(request.values.get("desde") or "").strip(),
        hasta=(request.values.get("hasta") or "").strip(),
        huerto=(request.values.get("huerto") or "").strip(),
    )


def _rango_historial(demo, conn):
    """Desde, hasta y huerto del filtro. Sin fechas, cubre todo el historial."""
    from demo_web.services.registro_riego import migrar_tabla

    hoy = hoy_demo(demo)
    migrar_tabla(conn)
    row = conn.execute("SELECT MIN(fecha), MAX(fecha) FROM riego").fetchone()
    fmin = parse_date(str(row[0])[:10] if row and row[0] else "", hoy)
    fmax = parse_date(str(row[1])[:10] if row and row[1] else "", hoy)
    fi = parse_date(request.args.get("desde"), fmin)
    ff = parse_date(request.args.get("hasta"), max(hoy, fmax))
    if fi > ff:
        fi, ff = ff, fi
    huerto = (request.args.get("huerto") or "").strip()
    return fi, ff, huerto


def _huertos_filtro(conn) -> list[str]:
    from demo_web.services.registro_riego import huertos_para_formulario

    vistos: dict[str, str] = {}
    for h in huertos_para_formulario():
        nombre = str(h or "").strip()
        clave = nombre.upper()
        if clave and clave not in vistos:
            vistos[clave] = nombre
    rows = conn.execute(
        "SELECT DISTINCT TRIM(huerto) FROM riego WHERE TRIM(COALESCE(huerto, '')) != ''"
    ).fetchall()
    for (h,) in rows:
        nombre = str(h or "").strip()
        clave = nombre.upper()
        if clave and clave not in vistos:
            vistos[clave] = nombre
    pedido = (request.args.get("huerto") or "").strip()
    if pedido and pedido.upper() not in vistos:
        vistos[pedido.upper()] = pedido
    return [vistos[k] for k in sorted(vistos)]


def _huerto_canon(pedido: str, opciones: list[str]) -> str:
    clave = (pedido or "").strip().upper()
    if not clave:
        return ""
    for h in opciones:
        if h.upper() == clave:
            return h
    return pedido.strip()


def _blob_historial(demo, rows, fi, ff, huerto: str) -> bytes | None:
    import pandas as pd

    if not rows:
        return None
    df = pd.DataFrame(
        [
            {
                "N°": r["codigo"],
                "Fecha": r["fecha"],
                "Huerto": r["huerto"],
                "ha": r.get("ha_fmt") or "",
                "Modo": r["modo_txt"],
                "Horas": r["horas"],
                "m3": r["m3"],
                "Fertilizacion": r["fert_txt"],
                "Regador": r["regador"],
                "Origen": r["origen"],
            }
            for r in rows
        ]
    )
    titulo = f"HISTORIAL DE RIEGO {fi.strftime('%d-%m-%Y')} A {ff.strftime('%d-%m-%Y')}"
    if huerto:
        titulo += f" - {huerto}"
    generar = getattr(demo, "generar_pdf_blob", None)
    if not generar:
        return None
    blob = generar(df, titulo, incluir_precios=False)
    return blob or None


def _pdf_historial(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    from demo_web.services.registro_riego import listar_historial

    conn = demo.conectar_db()
    try:
        fi, ff, pedido = _rango_historial(demo, conn)
        huerto = _huerto_canon(pedido, _huertos_filtro(conn))
        rows = listar_historial(
            conn,
            limite=None,
            desde=fi.isoformat(),
            hasta=ff.isoformat(),
            huerto=huerto or None,
        )
        blob = _blob_historial(demo, rows, fi, ff, huerto)
    finally:
        conn.close()
    if not blob:
        flash("No hay registros para el PDF.", "warning")
        return _volver_historial()
    return send_file(
        BytesIO(blob),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="historial_riego.pdf",
        max_age=0,
    )


def gather_riego(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    from demo_web.services.registro_riego import (
        contar_pendientes,
        config_riego_cc_para_formulario,
        fertilizantes_bodega_para_formulario,
        habilitado,
        huertos_para_formulario,
        links_personales_regadores,
        links_personales_regadores_demo,
        listar_bitacora,
        listar_config_riego_cc,
        listar_historial,
        resumen_npk_por_huerto,
    )

    sec_in = (request.values.get("sec") or request.args.get("sec") or "historial").strip()
    sub_in = (request.values.get("sub") or "").strip()
    lc = is_concepcion_tenant()
    if lc:
        secciones = list(SECCIONES_LC)
        sec, sub = _canon_lc(sec_in, sub_in)
    else:
        secciones = list(SECCIONES)
        if not habilitado():
            secciones = [s for s in secciones if s[0] != "bitacora"]
        sec = sec_in if sec_in in {k for k, _ in secciones} else "historial"
        sub = ""

    conn = demo.conectar_db()
    try:
        ctx: dict = {
            "secciones": secciones,
            "sec_activa": sec,
            "solo_lectura": demo.es_solo_lectura(),
            "huertos": huertos_para_formulario(),
            "form_fecha": hoy_demo(demo).isoformat(),
            "fertilizantes": fertilizantes_bodega_para_formulario(),
            "riego_cc_config": config_riego_cc_para_formulario(),
            "sub_activa": sub,
            "riego_lc": lc,
            "regar_sub": REGAR_SUB if lc else (),
            "armado_sub": ARMADO_SUB if lc else (),
        }
        n_pend = contar_pendientes(conn) if habilitado() else 0
        ctx["riego_pendientes"] = n_pend
        ctx["riego_desfase"] = n_pend > 0

        if sec == "historial":
            fi, ff, pedido = _rango_historial(demo, conn)
            opciones = _huertos_filtro(conn)
            huerto = _huerto_canon(pedido, opciones)
            rows = listar_historial(
                conn,
                limite=None,
                desde=fi.isoformat(),
                hasta=ff.isoformat(),
                huerto=huerto or None,
            )
            ctx["historial_rows"] = rows
            ctx["npk_resumen"] = resumen_npk_por_huerto(
                conn,
                desde=fi.isoformat(),
                hasta=ff.isoformat(),
                huerto=huerto or None,
            )
            ctx["bitacora_puede_autorizar"] = demo.es_admin() and not demo.es_solo_lectura()
            ctx["filtro_desde"] = fi.isoformat()
            ctx["filtro_hasta"] = ff.isoformat()
            ctx["filtro_huerto"] = huerto
            ctx["filtro_huertos"] = opciones
            ctx["n_registros"] = len(rows)
            if rows:
                pdf_args = {
                    "sec": "historial",
                    "pdf": "1",
                    "desde": fi.isoformat(),
                    "hasta": ff.isoformat(),
                }
                if huerto:
                    pdf_args["huerto"] = huerto
                ctx["pdf_historial_url"] = url_for("modules.riego", **pdf_args)
            else:
                ctx["pdf_historial_url"] = None
        elif sec == "hoy":
            from demo_web.services.hydrawise_riego import (
                contexto_control_hydra_ui,
                sectores_para_link_riego,
            )

            puede = demo.es_admin() and not demo.es_solo_lectura()
            ctx.update(
                contexto_control_hydra_ui(
                    conn, user_email or "admin", auto_sync=True
                )
            )
            ctx.update(
                {
                    "hydra_ui_scope": "module",
                    "hydra_ui_sec": "hoy",
                    "hydra_vista": "hoy",
                    "hydra_puede_operar": puede,
                    "bitacora_habilitada": True,
                    "hydra_link_sectores": len(sectores_para_link_riego(conn)),
                    "bitacora_puede_autorizar": puede,
                    "bitacora_registros": listar_bitacora(conn),
                }
            )
        elif sec == "regar":
            from demo_web.services.hydrawise_riego import contexto_control_hydra_ui

            puede = demo.es_admin() and not demo.es_solo_lectura()
            ctx.update(
                contexto_control_hydra_ui(
                    conn, user_email or "admin", auto_sync=False
                )
            )
            ctx.update(
                {
                    "hydra_ui_scope": "module",
                    "hydra_ui_sec": "regar",
                    "hydra_ui_sub": sub,
                    "hydra_vista": sub,
                    "hydra_puede_operar": puede,
                }
            )
        elif sec == "armado" and sub == "sectores":
            import json

            from demo_web.services.hydrawise_riego import (
                get_api_key,
                get_controller_id,
                listar_colas_recientes,
                listar_zonas,
            )

            puede = demo.es_admin() and not demo.es_solo_lectura()
            zonas = listar_zonas(conn)
            for z in zonas:
                z["fert_json"] = json.dumps(
                    [
                        {
                            "producto_id": f["producto_id"],
                            "cantidad": f["cantidad"],
                            "dosis_ha": f.get("dosis_ha"),
                        }
                        for f in z.get("fertilizantes") or []
                    ],
                    ensure_ascii=False,
                )
            tiene_key = bool(get_api_key(conn))
            cid = get_controller_id(conn)
            ctx.update(
                {
                    "hydra_puede_editar": puede,
                    "hydra_zonas": zonas,
                    "hydra_zonas_activas": [
                        z
                        for z in zonas
                        if z.get("activo") and (z.get("huerto_cc") or "").strip()
                    ],
                    "hydra_colas": listar_colas_recientes(conn),
                    "hydra_api_ok": tiene_key,
                    "hydra_api_msg": (
                        "API key guardada. Use «Probar conexión» en Admin o acciones aquí "
                        "(no se consulta Hydrawise al abrir esta pestaña)."
                        if tiene_key
                        else "Configure API key en Administración → Hydrawise."
                    ),
                    "hydra_controller_id": cid,
                }
            )
        elif sec == "armado" and sub == "enlaces":
            es_demo = get_erp_app() == "demo"
            ctx.update(
                {
                    "bitacora_admin_links": demo.es_super_admin(),
                    "bitacora_links": (
                        links_personales_regadores_demo()
                        if es_demo and demo.es_super_admin()
                        else links_personales_regadores()
                        if demo.es_super_admin()
                        else []
                    ),
                    "bitacora_links_demo": es_demo,
                }
            )
        elif sec == "armado" and sub == "parametros":
            ctx["riego_config_rows"] = (
                listar_config_riego_cc() if demo.es_super_admin() else []
            )
        elif sec == "armado" and sub == "manual":
            ctx["form_fecha"] = hoy_demo(demo).isoformat()
        elif sec == "bitacora" and habilitado():
            es_demo = get_erp_app() == "demo"
            hydra_link_n = 0
            if is_concepcion_tenant():
                from demo_web.services.hydrawise_riego import sectores_para_link_riego

                hydra_link_n = len(sectores_para_link_riego(conn))
            ctx.update(
                {
                    "bitacora_habilitada": True,
                    "hydra_link_sectores": hydra_link_n,
                    "bitacora_admin_links": demo.es_super_admin(),
                    "bitacora_puede_autorizar": demo.es_admin() and not demo.es_solo_lectura(),
                    "bitacora_registros": listar_bitacora(conn),
                    "bitacora_links": (
                        links_personales_regadores_demo()
                        if es_demo and demo.es_super_admin()
                        else links_personales_regadores()
                        if demo.es_super_admin()
                        else []
                    ),
                    "bitacora_links_demo": es_demo,
                    "riego_config_rows": listar_config_riego_cc() if demo.es_super_admin() else [],
                }
            )
        elif sec == "manual":
            ctx["form_fecha"] = hoy_demo(demo).isoformat()

        return ctx
    finally:
        conn.close()


def _post_manual(demo, conn, user_email: str) -> dict:
    from demo_web.services.registro_riego import parse_fertilizantes_request, registrar_manual

    fecha = request.form.get("fecha") or str(hoy_demo(demo))
    huerto = request.form.get("huerto") or ""
    try:
        horas = float((request.form.get("horas") or "0").replace(",", "."))
    except ValueError:
        horas = 0.0
    try:
        m3 = float((request.form.get("m3") or "0").replace(",", "."))
    except ValueError:
        m3 = 0.0
    modo_riego = (request.form.get("modo_riego") or "horas").strip().lower()
    regador = (request.form.get("regador") or user_email).strip()
    con_fert = request.form.get("con_fertilizacion") == "1"
    fert_lineas = parse_fertilizantes_request(request.form) if con_fert else None

    if con_fert and not fert_lineas:
        return {"ok": False, "msg": "Agregue al menos un fertilizante con cantidad."}

    return registrar_manual(
        fecha,
        huerto,
        horas,
        m3,
        regador,
        user_email,
        fertilizantes=fert_lineas,
        modo_riego=modo_riego,
    )


def view(user_email: str, user_rol: str):
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)

    if request.method == "POST":
        action = request.form.get("action", "")
        if demo.es_solo_lectura():
            flash("Modo solo lectura: no puede modificar datos.", "warning")
            sec = request.form.get("sec") or "historial"
            sub = request.form.get("sub") or ""
            if is_concepcion_tenant():
                sec, sub = _canon_lc(sec, sub)
            else:
                sub = ""
            return _volver(sec, sub)

        if action == "registrar_manual":
            conn = demo.conectar_db()
            try:
                result = _post_manual(demo, conn, user_email)
            finally:
                conn.close()
            flash(result["msg"], "success" if result["ok"] else "danger")
            if is_concepcion_tenant():
                return _volver("armado", "manual")
            return _volver("manual")

        if action == "autorizar_riego":
            if not demo.es_admin():
                flash("Solo un administrador puede autorizar.", "danger")
            else:
                from demo_web.services.registro_riego import autorizar_registro

                codigo = (request.form.get("codigo") or "").strip()
                result = autorizar_registro(codigo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
            if is_concepcion_tenant():
                return _volver("hoy")
            return _volver("bitacora")

        if action == "rechazar_riego":
            if not demo.es_admin():
                flash("Solo un administrador puede rechazar.", "danger")
            else:
                from demo_web.services.registro_riego import rechazar_registro

                codigo = (request.form.get("codigo") or "").strip()
                motivo = (request.form.get("motivo") or "").strip()
                result = rechazar_registro(codigo, user_email, motivo=motivo)
                flash(result["msg"], "success" if result["ok"] else "danger")
            if is_concepcion_tenant():
                return _volver("hoy")
            return _volver("bitacora")

        if action == "confirmar_fert_hydra":
            if not demo.es_admin():
                flash("Solo un administrador puede confirmar fertirriego HYDRA.", "danger")
            else:
                from demo_web.services.registro_riego import confirmar_fert_hydra

                codigo = (request.form.get("codigo") or "").strip()
                result = confirmar_fert_hydra(codigo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return _volver_historial()

        if action == "modificar_fert_hydra":
            if not demo.es_admin():
                flash("Solo un administrador puede modificar fertirriego HYDRA.", "danger")
            else:
                from demo_web.services.registro_riego import (
                    modificar_fert_hydra,
                    parse_fertilizantes_request,
                )

                codigo = (request.form.get("codigo") or "").strip()
                con_fert = request.form.get("con_fertilizacion") == "1"
                fert = parse_fertilizantes_request(request.form) if con_fert else []
                result = modificar_fert_hydra(
                    codigo,
                    user_email,
                    fert,
                    con_fertilizacion=con_fert,
                )
                flash(result["msg"], "success" if result["ok"] else "danger")
            return _volver_historial()

        if is_concepcion_tenant() and action.startswith("hydra_"):
            sec_hydra, sub_hydra = _canon_post_hydra(
                request.form.get("sec") or "hydra",
                request.form.get("sub") or "",
            )
            if not demo.es_admin():
                flash("Solo administradores pueden operar Hydra.", "danger")
                return _volver(sec_hydra, sub_hydra)
            conn = demo.conectar_db()
            try:
                from demo_web.services import hydrawise_riego as hw
                from demo_web.services.registro_riego import parse_fertilizantes_request

                result = {"ok": False, "msg": "Acción no reconocida."}
                if action == "hydra_sync":
                    result = hw.sincronizar_hydrawise(conn, user_email, force=True)
                elif action == "hydra_import_zonas":
                    result = hw.importar_zonas_desde_api(conn)
                elif action == "hydra_guardar_zona":
                    result = hw.guardar_mapeo_zona(
                        conn,
                        int(request.form.get("relay_id") or 0),
                        alias=request.form.get("alias") or "",
                        huerto_cc=request.form.get("huerto_cc") or "",
                        modo_riego=request.form.get("modo_riego") or "horas",
                        activo=request.form.get("activo") == "1",
                        link_riego=request.form.get("link_riego") == "1",
                        fert_json=request.form.get("fert_json") or "[]",
                    )
                elif action == "hydra_editar_fert_item":
                    item_id = int(request.form.get("cola_item_id") or 0)
                    con_fert = request.form.get("con_fertilizacion") == "1"
                    fert = parse_fertilizantes_request(request.form) if con_fert else []
                    result = hw.editar_fert_item_cola(
                        conn,
                        item_id,
                        con_fertilizacion=con_fert,
                        fertilizantes=fert,
                        usuario=user_email,
                    )
                elif action == "hydra_regar_ahora":
                    demo_mod = get_demo_module()
                    inicio = demo_mod.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
                    lineas = hw.parse_cola_lineas_form(request.form)
                    result = hw.crear_cola(
                        conn,
                        tipo="run_now",
                        inicio_programa=inicio,
                        lineas=lineas,
                        usuario=user_email,
                        regador_nombre=user_email,
                    )
                    if result.get("ok"):
                        sync = hw.sincronizar_hydrawise(conn, user_email, force=True)
                        result = {
                            "ok": sync.get("ok", True),
                            "msg": result.get("msg", "") + " " + sync.get("msg", ""),
                        }
                elif action == "hydra_programar":
                    inicio = (request.form.get("inicio_programa") or "").strip().replace("T", " ")
                    if len(inicio) == 16:
                        inicio += ":00"
                    lineas = hw.parse_cola_lineas_form(request.form)
                    result = hw.crear_cola(
                        conn,
                        tipo="programado",
                        inicio_programa=inicio,
                        lineas=lineas,
                        usuario=user_email,
                        regador_nombre=user_email,
                    )
                    if result.get("ok"):
                        sync = hw.sincronizar_hydrawise(conn, user_email, force=True)
                        result = {
                            "ok": sync.get("ok", True),
                            "msg": result.get("msg", "") + " " + sync.get("msg", ""),
                        }
                elif action == "hydra_parar":
                    result = hw.parar_riego_manual(conn, user_email, user_email)
                elif action == "hydra_cancelar_cola":
                    result = hw.cancelar_cola_manual(conn, user_email, user_email)
                elif action == "hydra_pausar":
                    result = hw.pausar_sector_cola(
                        conn, int(request.form.get("cola_item_id") or 0), user_email, user_email
                    )
                elif action == "hydra_reanudar":
                    result = hw.reanudar_sector_cola(
                        conn, int(request.form.get("cola_item_id") or 0), user_email, user_email
                    )
                elif action == "hydra_detener_sector":
                    result = hw.detener_sector_cola(
                        conn, int(request.form.get("cola_item_id") or 0), user_email, user_email
                    )
                elif action == "hydra_cancelar_sector":
                    result = hw.cancelar_sector_en_cola(
                        conn, int(request.form.get("cola_item_id") or 0), user_email, user_email
                    )
            finally:
                conn.close()
            flash(result.get("msg", ""), "success" if result.get("ok") else "danger")
            return _volver(sec_hydra, sub_hydra)

    sec_pdf = (request.args.get("sec") or "historial").strip()
    if is_concepcion_tenant():
        sec_pdf, _ = _canon_lc(sec_pdf, request.args.get("sub") or "")
    elif sec_pdf not in {k for k, _ in SECCIONES}:
        sec_pdf = "historial"
    if request.args.get("pdf") == "1" and sec_pdf == "historial":
        return _pdf_historial(user_email, user_rol)

    ctx = gather_riego(user_email, user_rol)
    return render_template(
        "modules/riego.html",
        page_title="Riego",
        active_key="Riego",
        title="💧 Riego",
        **ctx,
    )
