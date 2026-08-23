from __future__ import annotations

from flask import flash, render_template, request

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("historial", "📊 HISTORIAL"),
    ("manual", "✏️ REGISTRO MANUAL"),
    ("bitacora", "🔗 LINK RIEGO"),
]


def gather_riego(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    from demo_web.services.registro_riego import (
        contar_pendientes,
        config_riego_cc_para_formulario,
        fertilizantes_bodega_para_formulario,
        guardar_surcos_total_cc,
        habilitado,
        huertos_para_formulario,
        links_personales_regadores,
        listar_bitacora,
        listar_config_riego_cc,
        listar_historial,
    )

    sec = request.values.get("sec") or request.args.get("sec", "historial")
    secciones = list(SECCIONES)
    if not habilitado():
        secciones = [s for s in secciones if s[0] != "bitacora"]
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
        elif sec == "bitacora" and habilitado():
            ctx.update(
                {
                    "bitacora_habilitada": True,
                    "bitacora_admin_links": demo.es_super_admin(),
                    "bitacora_puede_autorizar": demo.es_admin() and not demo.es_solo_lectura(),
                    "bitacora_registros": listar_bitacora(conn),
                    "bitacora_links": links_personales_regadores() if demo.es_super_admin() else [],
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
    surcos_raw = (request.form.get("surcos") or "").strip()
    surcos = None
    if modo_riego == "surcos" and surcos_raw:
        try:
            surcos = float(surcos_raw.replace(",", "."))
        except ValueError:
            surcos = None
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
        surcos=surcos,
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

        if action == "guardar_surcos_riego":
            if not demo.es_super_admin():
                flash("Solo super-admin puede configurar surcos.", "danger")
            else:
                from demo_web.services.registro_riego import guardar_surcos_total_cc

                cc = (request.form.get("centro_costo") or "").strip()
                try:
                    total = int(request.form.get("surcos_total") or "0")
                except ValueError:
                    total = 0
                result = guardar_surcos_total_cc(cc, total)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="bitacora")

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

    ctx = gather_riego(user_email, user_rol)
    return render_template(
        "modules/riego.html",
        page_title="Riego",
        active_key="Riego",
        title="💧 Riego",
        **ctx,
    )
