from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template, request, url_for

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
    try:
        return bodega_stock_rapido.render_public(tok)
    except Exception:
        current_app.logger.exception("stock_bodega_link kardex")
        return (
            render_template(
                "stock_bodega_rapido.html",
                page_title="Stock bodega",
                items=[],
                filtro_q="",
                pid=0,
                kardex_error="No se pudo cargar el kardex. Reintente o use Bodega en el ERP.",
                kardex_producto=None,
                kardex_rows=[],
                kardex_lc_pendientes=[],
                url_stock_list=url_for("stock_bodega_link.formulario", t=tok),
                link_tok=tok,
                link_mode=True,
                actualizado="",
                erp_title="La Concepción",
            ),
            500,
        )
