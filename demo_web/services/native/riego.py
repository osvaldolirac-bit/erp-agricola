from __future__ import annotations

from io import BytesIO

import pandas as pd
from flask import flash, render_template, request, send_file, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.erp_loader import get_erp_app
from demo_web.services.module_runner import pdf_download_url, redirect_module, store_pdf
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("historial", "📊 HISTORIAL"),
    ("manual", "✏️ REGISTRO MANUAL"),
    ("bitacora", "🔗 LINK RIEGO"),
]

_PDF_HISTORIAL_FILENAME = "HISTORIAL_RIEGO_LA_CONCEPCION.pdf"


def _filas_pdf_historial(conn, demo) -> list[dict[str, str]]:
    from demo_web.services.registro_riego import listar_historial

    rows = listar_historial(conn, limite=500, demo=demo)
    out: list[dict[str, str]] = []
    for r in rows:
        out.append(
            {
                "N": str(r.get("codigo") or ""),
                "FECHA": str(r.get("fecha") or ""),
                "HUERTO": str(r.get("huerto") or ""),
                "ha": str(r.get("ha_fmt") or "—"),
                "MODO": str(r.get("modo_txt") or ""),
                "HORAS": str(r.get("horas") or ""),
                "m3": str(r.get("m3") or ""),
                "FERTILIZACION": str(r.get("fert_txt") or "")[:80],
                "REGADOR": str(r.get("regador") or ""),
                "ORIGEN": str(r.get("origen") or ""),
                "NOTA": str(r.get("nota") or "") or "—",
            }
        )
    return out


def generar_pdf_historial_blob(demo, conn) -> bytes | None:
    records = _filas_pdf_historial(conn, demo)
    if not records:
        return None
    df = pd.DataFrame(records)
    blob = demo.generar_pdf_blob(df, "HISTORIAL DE RIEGO", incluir_precios=False)
    return blob


def export_historial_pdf(user_email: str, user_rol: str):
    """Descarga PDF bajo demanda (evita fallos silenciosos al renderizar la pestaña)."""
    from werkzeug.utils import secure_filename

    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    conn = demo.conectar_db()
    try:
        blob = generar_pdf_historial_blob(demo, conn)
    finally:
        conn.close()
    if not blob:
        from flask import abort

        abort(404)
    fname = secure_filename(_PDF_HISTORIAL_FILENAME) or "HISTORIAL_RIEGO.pdf"
    return send_file(
        BytesIO(blob),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=fname,
        max_age=0,
    )


def _pdf_historial_riego(demo, conn) -> str | None:
    blob = generar_pdf_historial_blob(demo, conn)
    if not blob:
        return None
    token = store_pdf(blob, _PDF_HISTORIAL_FILENAME)
    return pdf_download_url(token, _PDF_HISTORIAL_FILENAME)


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
            ctx["historial_rows"] = listar_historial(conn, demo=demo)
            ctx["npk_resumen"] = resumen_npk_por_huerto(conn)
            ctx["pdf_historial_filename"] = _PDF_HISTORIAL_FILENAME
            ctx["pdf_historial_url"] = url_for("modules.riego_pdf_historial")
            try:
                ctx["pdf_historial_cache_url"] = _pdf_historial_riego(demo, conn)
            except Exception:
                ctx["pdf_historial_cache_url"] = None
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

    nota = (request.form.get("nota") or "").strip()

    return registrar_manual(
        fecha,
        huerto,
        horas,
        m3,
        regador,
        user_email,
        fertilizantes=fert_lineas,
        modo_riego=modo_riego,
        nota=nota,
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
