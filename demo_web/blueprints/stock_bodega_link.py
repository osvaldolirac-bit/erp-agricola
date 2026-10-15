from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from demo_web.services.erp_loader import bind_tenant_context
from demo_web.services.native import bodega_stock_rapido
from demo_web.services.stock_bodega_link import habilitado, token_valido

bp = Blueprint("stock_bodega_link", __name__)


def _token_request() -> str | None:
    return (request.args.get("t") or "").strip() or None


@bp.route("/stock-bodega", methods=["GET"])
def formulario():
    """Stock + kardex móvil LC vía token (WhatsApp / favoritos)."""
    bind_tenant_context("concepcion")
    if not habilitado():
        abort(404)
    tok = _token_request()
    if not token_valido(tok):
        return render_template("registro_riego/denied.html"), 403
    return bodega_stock_rapido.render_public(tok)
