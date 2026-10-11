from __future__ import annotations

from flask import flash, render_template, request

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
SECCION_HYDRA = ("hydra", "🌐 HYDRA")


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

    sec = request.values.get("sec") or request.args.get("sec", "historial")
    secciones = list(SECCIONES)
    if not habilitado():
        secciones = [s for s in secciones if s[0] != "bitacora"]
    if is_concepcion_tenant():
        secciones.append(SECCION_HYDRA)
    if sec not in {k for k, _ in secciones}:
        sec = "historial"

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
        }
        n_pend = contar_pendientes(conn) if habilitado() else 0
        ctx["riego_pendientes"] = n_pend
        ctx["riego_desfase"] = n_pend > 0

        if sec == "historial":
            ctx["historial_rows"] = listar_historial(conn)
            ctx["npk_resumen"] = resumen_npk_por_huerto(conn)
            ctx["bitacora_puede_autorizar"] = demo.es_admin() and not demo.es_solo_lectura()
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
        elif sec == "hydra" and is_concepcion_tenant():
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
                        z for z in zonas if z.get("activo") and (z.get("huerto_cc") or "").strip()
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
            return redirect_module("riego", sec=sec)

        if action == "registrar_manual":
            conn = demo.conectar_db()
            try:
                result = _post_manual(demo, conn, user_email)
            finally:
                conn.close()
            flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="manual")

        if action == "autorizar_riego":
            if not demo.es_admin():
                flash("Solo un administrador puede autorizar.", "danger")
            else:
                from demo_web.services.registro_riego import autorizar_registro

                codigo = (request.form.get("codigo") or "").strip()
                result = autorizar_registro(codigo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="bitacora")

        if action == "rechazar_riego":
            if not demo.es_admin():
                flash("Solo un administrador puede rechazar.", "danger")
            else:
                from demo_web.services.registro_riego import rechazar_registro

                codigo = (request.form.get("codigo") or "").strip()
                motivo = (request.form.get("motivo") or "").strip()
                result = rechazar_registro(codigo, user_email, motivo=motivo)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="bitacora")

        if action == "confirmar_fert_hydra":
            if not demo.es_admin():
                flash("Solo un administrador puede confirmar fertirriego HYDRA.", "danger")
            else:
                from demo_web.services.registro_riego import confirmar_fert_hydra

                codigo = (request.form.get("codigo") or "").strip()
                result = confirmar_fert_hydra(codigo, user_email)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="historial")

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
            return redirect_module("riego", sec="historial")

        if is_concepcion_tenant() and action.startswith("hydra_"):
            if not demo.es_admin():
                flash("Solo administradores pueden operar Hydra.", "danger")
                return redirect_module("riego", sec="hydra")
            conn = demo.conectar_db()
            try:
                from demo_web.services import hydrawise_riego as hw

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
                elif action == "hydra_regar_ahora":
                    demo_mod = get_demo_module()
                    inicio = demo_mod.hora_chile().strftime("%Y-%m-%d %H:%M:%S")
                    result = hw.crear_cola_desde_form(
                        request.form,
                        tipo="run_now",
                        usuario=user_email,
                        inicio_programa=inicio,
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
                    result = hw.crear_cola_desde_form(
                        request.form,
                        tipo="programado",
                        usuario=user_email,
                        inicio_programa=inicio,
                    )
                elif action == "hydra_parar":
                    result = hw.parar_riego_manual(conn, user_email, user_email)
                elif action == "hydra_cancelar_cola":
                    result = hw.cancelar_cola_manual(conn, user_email, user_email)
            finally:
                conn.close()
            flash(result.get("msg", ""), "success" if result.get("ok") else "danger")
            return redirect_module("riego", sec="hydra")

    ctx = gather_riego(user_email, user_rol)
    return render_template(
        "modules/riego.html",
        page_title="Riego",
        active_key="Riego",
        title="💧 Riego",
        **ctx,
    )
