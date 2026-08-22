from __future__ import annotations

from flask import flash, render_template, request

from demo_web.services.demo_loader import bind_user_session, get_demo_module
from demo_web.services.module_runner import redirect_module
from demo_web.services.native._helpers import hoy_demo, parse_date

SECCIONES = [
    ("manual", "✏️ REGISTRO MANUAL"),
    ("ingreso", "🔗 INGRESO"),
    ("historial", "📊 HISTORIAL"),
]


def gather_riego(user_email: str, user_rol: str) -> dict:
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    from demo_web.services.registro_riego import (
        contar_pendientes,
        habilitado,
        huertos_para_formulario,
        links_personales_regadores,
        listar_bitacora,
        listar_historial,
    )

    sec = request.values.get("sec") or request.args.get("sec", "historial")
    secciones = list(SECCIONES)
    if not habilitado():
        secciones = [s for s in secciones if s[0] != "ingreso"]
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
        }
        n_pend = contar_pendientes(conn) if habilitado() else 0
        ctx["riego_pendientes"] = n_pend
        ctx["riego_desfase"] = n_pend > 0

        if sec == "historial":
            ctx["historial_rows"] = listar_historial(conn)
        elif sec == "ingreso" and habilitado():
            ctx.update(
                {
                    "ingreso_habilitado": True,
                    "ingreso_admin_links": demo.es_super_admin(),
                    "ingreso_puede_autorizar": demo.es_admin() and not demo.es_solo_lectura(),
                    "ingreso_registros": listar_bitacora(conn),
                    "ingreso_links": links_personales_regadores() if demo.es_super_admin() else [],
                }
            )
        elif sec == "manual":
            ctx["form_fecha"] = hoy_demo(demo).isoformat()

        return ctx
    finally:
        conn.close()


def _post_manual(demo, conn, user_email: str) -> dict:
    from demo_web.services.registro_riego import registrar_manual

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
    regador = (request.form.get("regador") or user_email).strip()
    con_fert = request.form.get("con_fertilizacion") == "1"
    dosis = total = None
    if con_fert:
        try:
            dosis = float((request.form.get("fert_dosis_ha") or "0").replace(",", "."))
        except ValueError:
            dosis = None
        try:
            total = float((request.form.get("fert_total") or "0").replace(",", "."))
        except ValueError:
            total = None
    if horas <= 0 and m3 <= 0:
        return {"ok": False, "msg": "Indique horas o m³ mayores a cero."}
    return registrar_manual(
        fecha,
        huerto,
        horas,
        m3,
        regador,
        user_email,
        fert_dosis_ha=dosis,
        fert_total=total,
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
            return redirect_module("riego", sec="ingreso")

        if action == "rechazar_riego":
            if not demo.es_admin():
                flash("Solo un administrador puede rechazar.", "danger")
            else:
                from demo_web.services.registro_riego import rechazar_registro

                codigo = (request.form.get("codigo") or "").strip()
                motivo = (request.form.get("motivo") or "").strip()
                result = rechazar_registro(codigo, user_email, motivo=motivo)
                flash(result["msg"], "success" if result["ok"] else "danger")
            return redirect_module("riego", sec="ingreso")

    ctx = gather_riego(user_email, user_rol)
    return render_template(
        "modules/riego.html",
        page_title="Riego",
        active_key="Riego",
        title="💧 Riego",
        **ctx,
    )
