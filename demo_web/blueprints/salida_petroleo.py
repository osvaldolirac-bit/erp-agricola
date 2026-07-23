from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from demo_web.auth.decorators import login_required
from demo_web.services.demo_loader import get_demo_module
from demo_web.services.salida_petroleo import (
    cuarteles_para_formulario,
    habilitado,
    maquinaria_para_formulario,
    registrar_salida,
    responsables_autorizados_para_formulario,
    token_valido,
)

bp = Blueprint("salida_petroleo", __name__)


def _token_request() -> str | None:
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


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
    responsables_map = {r["id"]: r["nombre"] for r in responsables_opts}

    ok = False
    mail_ok = None
    error = None
    codigo = None
    aviso_duplicado = None
    codigo_duplicado = None
    form_litros = ""
    form_maquinaria = ""
    form_responsable = ""
    form_cuarteles_sel: list[str] = []

    if request.method == "POST":
        if (request.form.get("website") or "").strip():
            ok = True
        else:
            try:
                litros = float((request.form.get("litros") or "0").replace(",", "."))
            except ValueError:
                litros = 0.0
            maquinaria_cod = (request.form.get("maquinaria") or "").strip()
            maquinaria = maquinaria_map.get(maquinaria_cod, "")
            responsable_id = (request.form.get("responsable") or "").strip()
            responsable = responsables_map.get(responsable_id, "")
            sel = [c for c in request.form.getlist("cuarteles") if c in cuarteles_opts]
            confirmar = request.form.get("confirmar_duplicado") == "1"
            form_litros = request.form.get("litros") or ""
            form_maquinaria = maquinaria_cod
            form_responsable = responsable_id
            form_cuarteles_sel = sel

            if litros <= 0:
                error = "Indique litros mayores a cero."
            elif not sel:
                error = "Seleccione al menos un cuartel."
            elif not maquinaria:
                error = "Seleccione un equipo de la lista."
            elif not responsables_opts:
                error = "No hay responsables autorizados. En RRHH → Personal marque trabajadores o agregue dueños."
            elif not responsable:
                error = "Seleccione un responsable autorizado."
            else:
                res = registrar_salida(
                    litros, sel, maquinaria, responsable, confirmar_duplicado=confirmar
                )
                if res.get("duplicado"):
                    aviso_duplicado = res.get("msg")
                    codigo_duplicado = res.get("codigo_duplicado")
                elif res.get("ok"):
                    ok = True
                    mail_ok = res.get("mail_ok")
                    codigo = res.get("codigo")

    return render_template(
        "salida_petroleo/form.html",
        token=tok,
        cuarteles=cuarteles_opts,
        maquinaria=maquinaria_opts,
        responsables=responsables_opts,
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


@bp.route("/salida-petroleo/qr")
@login_required
def qr_admin():
    """Legacy: redirige a la pestaña Bitácora campo en Petróleo."""
    if not habilitado():
        abort(404)
    demo = get_demo_module()
    if not demo.es_super_admin():
        abort(403)
    return redirect(url_for("modules.petroleo", sec="bitacora"))
