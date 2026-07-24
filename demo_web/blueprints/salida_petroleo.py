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
from demo_web.services.salida_petroleo import (
    aplicar_cookie_operador,
    cuarteles_para_formulario,
    habilitado,
    leer_operador_cookie,
    maquinaria_para_formulario,
    registrar_salida,
    resolver_responsable_por_id,
    responsables_autorizados_para_formulario,
    token_valido,
)

bp = Blueprint("salida_petroleo", __name__)

# Nombre que Safari/autofill no suelen completar (evitar falso "Registrado").
_HONEYPOT_FIELD = "sp_hp_x9f2"


def _token_request() -> str | None:
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


def _url_formulario(tok: str, **extra) -> str:
    return url_for("salida_petroleo.formulario", t=tok, **extra)


@bp.route("/salida-petroleo", methods=["GET", "POST"])
def formulario():
    if not habilitado():
        abort(404)
    tok = _token_request()
    if not token_valido(tok):
        return render_template("salida_petroleo/denied.html"), 403

    cuarteles_opts = cuarteles_para_formulario()
    maquinaria_opts = maquinaria_para_formulario()
    maquinaria_map = {m["codigo"]: m["etiqueta"] for m in maquinaria_opts}
    responsables_opts = responsables_autorizados_para_formulario()

    # Solo link personal (?op=) o cookie dejada por ese link. Sin selector público.
    op_query = resolver_responsable_por_id(request.args.get("op"), responsables_opts)
    op_cookie = leer_operador_cookie(responsables_opts)
    operador = op_query or op_cookie
    acceso_personal = bool(operador)

    ok = False
    mail_ok = None
    error = None
    codigo = None
    aviso_duplicado = None
    codigo_duplicado = None
    form_litros = ""
    form_maquinaria = ""
    form_responsable = (operador or {}).get("id", "")
    form_cuarteles_sel: list[str] = []
    cookie_op_id: str | None = None

    if request.method == "POST":
        hp = (request.form.get(_HONEYPOT_FIELD) or "").strip()
        try:
            litros = float((request.form.get("litros") or "0").replace(",", "."))
        except ValueError:
            litros = 0.0
        maquinaria_cod = (request.form.get("maquinaria") or "").strip()
        maquinaria = maquinaria_map.get(maquinaria_cod, "")
        # Ignorar responsable del form: solo vale el operador del link/cookie.
        operador_post = operador
        responsable = (operador_post or {}).get("nombre", "")
        sel = [c for c in request.form.getlist("cuarteles") if c in cuarteles_opts]
        confirmar = request.form.get("confirmar_duplicado") == "1"
        form_litros = request.form.get("litros") or ""
        form_maquinaria = maquinaria_cod
        form_responsable = (operador_post or {}).get("id", "")
        form_cuarteles_sel = sel

        # Honeypot: solo bloquear bots claros. Si hay payload válido, ignorar
        # (Safari a veces autocompleta campos ocultos y antes daba "Registrado" falso).
        bot_claro = bool(hp) and litros <= 0 and not sel and not maquinaria
        if bot_claro:
            ok = False
            error = None
        elif not acceso_personal:
            error = "Use su enlace personal para registrar una salida."
        elif litros <= 0:
            error = "Indique litros mayores a cero."
        elif not sel:
            error = "Seleccione al menos un cuartel."
        elif not maquinaria:
            error = "Seleccione un equipo de la lista."
        elif not responsables_opts:
            error = (
                "No hay responsables autorizados. En RRHH → Personal "
                "marque trabajadores o agregue dueños."
            )
        elif not responsable:
            error = "Use su enlace personal para registrar una salida."
        else:
            try:
                res = registrar_salida(
                    litros,
                    sel,
                    maquinaria,
                    responsable,
                    maquinaria_codigo=maquinaria_cod,
                    confirmar_duplicado=confirmar,
                )
            except Exception as exc:
                error = f"No se pudo guardar la bitácora: {exc}"
                res = {"ok": False}
            if res.get("duplicado"):
                aviso_duplicado = res.get("msg")
                codigo_duplicado = res.get("codigo_duplicado")
            elif res.get("ok"):
                ok = True
                mail_ok = res.get("mail_ok")
                codigo = res.get("codigo")
                cookie_op_id = (operador_post or {}).get("id")
                operador = operador_post
            elif not error:
                error = res.get("msg") or "No se pudo registrar la salida. Intente de nuevo."

    html = render_template(
        "salida_petroleo/form.html",
        token=tok,
        honeypot_field=_HONEYPOT_FIELD,
        cuarteles=cuarteles_opts,
        maquinaria=maquinaria_opts,
        responsables=responsables_opts,
        operador=operador,
        acceso_personal=acceso_personal,
        ok=ok,
        codigo=codigo,
        mail_ok=mail_ok,
        error=error,
        aviso_duplicado=aviso_duplicado,
        codigo_duplicado=codigo_duplicado,
        form_litros=form_litros,
        form_maquinaria=form_maquinaria,
        form_responsable=form_responsable,
        form_cuarteles_sel=form_cuarteles_sel,
    )
    resp = make_response(html)
    if cookie_op_id:
        aplicar_cookie_operador(resp, cookie_op_id)
    elif op_query:
        aplicar_cookie_operador(resp, op_query["id"])
    return resp


@bp.route("/salida-petroleo/qr")
@login_required
def qr_admin():
    """Legacy: redirige a la pestaña Salida QR en Petróleo."""
    if not habilitado():
        abort(404)
    demo = get_demo_module()
    if not demo.es_super_admin():
        abort(403)
    return redirect(url_for("modules.petroleo", sec="bitacora"))
