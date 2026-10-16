from __future__ import annotations

from flask import Blueprint, Response, abort, current_app, render_template, request, send_file, url_for
from io import BytesIO
from werkzeug.utils import secure_filename

from demo_web.services.erp_loader import bind_tenant_context
from demo_web.services.native import bodega_stock_rapido
from demo_web.services.stock_bodega_link import habilitado, token_valido

bp = Blueprint("stock_bodega_link", __name__)


def _token_request() -> str | None:
    return (request.args.get("t") or "").strip() or None


def _pdf_safe_name(name: str | None) -> str:
    safe = secure_filename((name or "documento.pdf").split("/")[-1]) or "documento.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = f"{safe}.pdf"
    return safe


@bp.route("/stock-bodega/pdf/<token>")
@bp.route("/stock-bodega/pdf/<token>/<path:download_name>")
def kardex_pdf(token: str, download_name: str | None = None):
    """Descarga PDF kardex/stock sin login ERP (requiere token del link bodega)."""
    bind_tenant_context("concepcion")
    if not habilitado():
        abort(404)
    if not token_valido(_token_request()):
        return render_template("registro_riego/denied.html"), 403
    from demo_web.services import module_runner as mr
    from demo_web.services.pdf_meta import stamp_pdf_title

    got = mr.get_pdf(token)
    if not got:
        return Response("PDF no encontrado o expirado.", status=404)
    blob, stored_name = got
    inline = request.args.get("inline") in ("1", "true", "yes")
    safe = _pdf_safe_name(download_name or stored_name)
    blob = stamp_pdf_title(blob, safe)
    return send_file(
        BytesIO(blob),
        mimetype="application/pdf",
        as_attachment=not inline,
        download_name=safe,
    )


@bp.route("/stock-bodega/visor/<token>")
@bp.route("/stock-bodega/visor/<token>/<path:download_name>")
def visor_pdf(token: str, download_name: str | None = None):
    """Visor móvil: volver al listado/kardex + imprimir (token link bodega)."""
    bind_tenant_context("concepcion")
    if not habilitado():
        abort(404)
    tok = _token_request()
    if not token_valido(tok):
        return render_template("registro_riego/denied.html"), 403

    from demo_web.services import module_runner as mr

    got = mr.get_pdf(token)
    if not got:
        return Response("PDF no encontrado o expirado.", status=404)
    _, stored_name = got
    fname = _pdf_safe_name(download_name or stored_name)
    q = (request.args.get("q") or "").strip()
    pid_raw = (request.args.get("pid") or "").strip()
    pid = int(pid_raw) if pid_raw.isdigit() else None

    if pid:
        back_url = url_for(
            "stock_bodega_link.formulario",
            t=tok,
            pid=pid,
            q=q or None,
        )
    else:
        back_url = url_for("stock_bodega_link.formulario", t=tok, q=q or None)

    pdf_embed_url = url_for(
        "stock_bodega_link.kardex_pdf",
        token=token,
        download_name=fname,
        t=tok,
        inline=1,
    )
    pdf_download_url = url_for(
        "stock_bodega_link.kardex_pdf",
        token=token,
        download_name=fname,
        t=tok,
    )
    return render_template(
        "stock_bodega_pdf_view.html",
        filename=fname,
        back_url=back_url,
        pdf_embed_url=pdf_embed_url,
        pdf_download_url=pdf_download_url,
        erp_title="La Concepción",
    )


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
                pdf_kardex_url=None,
                pdf_kardex_filename=None,
                pdf_stock_url=None,
                pdf_stock_filename=None,
                url_stock_list=url_for("stock_bodega_link.formulario", t=tok),
                link_tok=tok,
                link_mode=True,
                actualizado="",
                erp_title="La Concepción",
            ),
            500,
        )
