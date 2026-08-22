from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from demo_web.auth.decorators import login_required
from demo_web.services.demo_loader import get_demo_module
from demo_web.services.registro_riego import (
    aplicar_cookie_operador,
    habilitado,
    huertos_para_formulario,
    leer_operador_cookie,
    registrar_link,
    regadores_autorizados_para_formulario,
    resolver_regador_por_id,
    token_valido,
)

bp = Blueprint("registro_riego", __name__)

_HONEYPOT_FIELD = "sr_hp_x9f2"


def _token_request() -> str | None:
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


@bp.route("/registro-riego", methods=["GET", "POST"])
def formulario():
    if not habilitado():
        abort(404)
    tok = _token_request()
    if not token_valido(tok):
        return render_template("registro_riego/denied.html"), 403

    huertos = huertos_para_formulario()
    regadores_opts = regadores_autorizados_para_formulario()
    op_query = resolver_regador_por_id(request.args.get("op"), regadores_opts)
    op_cookie = leer_operador_cookie(regadores_opts)
    operador = op_query or op_cookie
    acceso_personal = bool(operador)

    ok = False
    mail_ok = None
    error = None
    codigo = None
    form_fecha = ""
    form_huerto = ""
    form_horas = ""
    form_m3 = ""
    form_dosis = ""
    form_total = ""
    form_con_fert = False

    if request.method == "POST":
        hp = (request.form.get(_HONEYPOT_FIELD) or "").strip()
        form_fecha = request.form.get("fecha") or ""
        form_huerto = request.form.get("huerto") or ""
        form_horas = request.form.get("horas") or ""
        form_m3 = request.form.get("m3") or ""
        form_dosis = request.form.get("fert_dosis_ha") or ""
        form_total = request.form.get("fert_total") or ""
        form_con_fert = request.form.get("con_fertilizacion") == "1"

        try:
            horas = float((form_horas or "0").replace(",", "."))
        except ValueError:
            horas = 0.0
        try:
            m3 = float((form_m3 or "0").replace(",", "."))
        except ValueError:
            m3 = 0.0
        dosis = None
        total = None
        if form_con_fert:
            try:
                dosis = float((form_dosis or "0").replace(",", ".")) if form_dosis else None
            except ValueError:
                dosis = None
            try:
                total = float((form_total or "0").replace(",", ".")) if form_total else None
            except ValueError:
                total = None

        bot_claro = bool(hp) and horas <= 0 and m3 <= 0 and not form_huerto
        if bot_claro:
            ok = False
            error = None
        elif not acceso_personal:
            error = "Use su enlace personal para registrar riego."
        elif not form_fecha:
            error = "Indique la fecha."
        elif form_huerto not in huertos:
            error = "Seleccione un huerto válido."
        elif horas <= 0 and m3 <= 0:
            error = "Indique horas de riego o m³ mayores a cero."
        elif not regadores_opts:
            error = "No hay regadores autorizados. En RRHH marque trabajadores como regador."
        else:
            try:
                res = registrar_link(
                    form_fecha,
                    form_huerto,
                    horas,
                    m3,
                    (operador or {}).get("nombre", ""),
                    fert_dosis_ha=dosis,
                    fert_total=total,
                )
            except Exception as exc:
                error = f"No se pudo guardar: {exc}"
                res = {"ok": False}
            if res.get("ok"):
                ok = True
                mail_ok = res.get("mail_ok")
                codigo = res.get("codigo")
                operador = operador

    html = render_template(
        "registro_riego/form.html",
        token=tok,
        honeypot_field=_HONEYPOT_FIELD,
        huertos=huertos,
        operador=operador,
        acceso_personal=acceso_personal,
        ok=ok,
        codigo=codigo,
        mail_ok=mail_ok,
        error=error,
        form_fecha=form_fecha,
        form_huerto=form_huerto,
        form_horas=form_horas,
        form_m3=form_m3,
        form_dosis=form_dosis,
        form_total=form_total,
        form_con_fert=form_con_fert,
    )
    resp = make_response(html)
    if ok and operador:
        aplicar_cookie_operador(resp, operador["id"])
    elif op_query:
        aplicar_cookie_operador(resp, op_query["id"])
    return resp


@bp.route("/registro-riego/links")
@login_required
def links_admin():
    if not habilitado():
        abort(404)
    demo = get_demo_module()
    if not demo.es_super_admin():
        abort(403)
    return redirect(url_for("modules.riego", sec="ingreso"))
