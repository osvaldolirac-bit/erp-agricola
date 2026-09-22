from __future__ import annotations

from datetime import timedelta

import pandas as pd
from flask import flash, render_template, request

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import pdf_download_url, redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("historial", "📊 HISTORIAL"),
    ("manual", "✏️ REGISTRO MANUAL"),
    ("bitacora", "🔗 LINK RIEGO"),
]

PDF_HISTORIAL_FILENAME = "RIEGO_HISTORIAL.pdf"


def _historial(demo, conn) -> dict:
    from demo_web.services.registro_riego import listar_historial, resumen_npk_por_huerto

    hoy = hoy_demo(demo)
    try:
        f_min_q = conn.execute("SELECT MIN(fecha) FROM riego").fetchone()[0]
        f_min_p = parse_date(f_min_q, hoy - timedelta(days=365)) if f_min_q else hoy - timedelta(days=365)
    except Exception:
        f_min_p = hoy - timedelta(days=365)

    fi = parse_date(request.args.get("desde"), f_min_p)
    ff = parse_date(request.args.get("hasta"), hoy)
    huerto = (request.args.get("huerto") or "TODOS").strip()
    origen = (request.args.get("origen") or "TODOS").strip()
    regador_q = (request.args.get("regador") or "").strip()

    fi_s, ff_s = str(fi), str(ff)
    huerto_f = None if huerto.upper() == "TODOS" else huerto
    origen_f = None if origen.upper() == "TODOS" else origen

    historial_rows = listar_historial(
        conn,
        desde=fi_s,
        hasta=ff_s,
        huerto=huerto_f,
        origen=origen_f,
        regador_q=regador_q or None,
    )
    npk_resumen = resumen_npk_por_huerto(
        conn,
        desde=fi_s,
        hasta=ff_s,
        huerto=huerto_f,
        origen=origen_f,
        regador_q=regador_q or None,
    )

    pdf_url = None
    if historial_rows:
        df = pd.DataFrame(
            [
                {
                    "N°": r["codigo"],
                    "FECHA": r["fecha"],
                    "HUERTO": r["huerto"],
                    "HORAS": r["horas"],
                    "M³": r["m3"],
                    "MODO": r.get("modo_txt", ""),
                    "FERTILIZACIÓN": r.get("fert_txt", ""),
                    "N (kg)": r.get("n_kg_fmt", "—"),
                    "N kg/ha": r.get("n_ha_fmt", "—"),
                    "P₂O₅ (kg)": r.get("p_kg_fmt", "—"),
                    "P kg/ha": r.get("p_ha_fmt", "—"),
                    "K₂O (kg)": r.get("k_kg_fmt", "—"),
                    "K kg/ha": r.get("k_ha_fmt", "—"),
                    "REGADOR": r["regador"],
                    "ORIGEN": r["origen"],
                }
                for r in historial_rows
            ]
        )
        titulo = f"HISTORIAL RIEGO ({fi.strftime('%d-%m-%Y')} — {ff.strftime('%d-%m-%Y')})"
        blob = demo.generar_pdf_blob(df, titulo, incluir_precios=False)
        if blob:
            pdf_url = pdf_download_url(store_pdf(blob, PDF_HISTORIAL_FILENAME), PDF_HISTORIAL_FILENAME)

    return {
        "historial_rows": historial_rows,
        "npk_resumen": npk_resumen,
        "filtro_desde": fi.isoformat(),
        "filtro_hasta": ff.isoformat(),
        "filtro_huerto": huerto,
        "filtro_origen": origen,
        "filtro_regador": regador_q,
        "historial_stats": {"total": len(historial_rows)},
        "pdf_historial_url": pdf_url,
        "pdf_historial_filename": PDF_HISTORIAL_FILENAME,
    }


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
            ctx.update(_historial(demo, conn))
        elif sec == "bitacora" and habilitado():
            es_demo = get_erp_app() == "demo"
            ctx.update(
                {
                    "bitacora_habilitada": True,
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

    ctx = gather_riego(user_email, user_rol)
    return render_template(
        "modules/riego.html",
        page_title="Riego",
        active_key="Riego",
        title="💧 Riego",
        **ctx,
    )
