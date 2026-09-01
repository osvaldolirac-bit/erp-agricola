from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, Response, abort, redirect, render_template, request, send_file, url_for

from demo_web.auth.decorators import login_required, module_required
from demo_web.services import module_runner as mr
from demo_web.services.native_registry import run_native_or_capture

bp = Blueprint("modules", __name__, url_prefix="/m")


def _route(slug: str):
    module_key, _ = mr.MODULES[slug]

    @login_required
    @module_required(module_key)
    def view():
        from flask import g

        return run_native_or_capture(slug, g.user["email"], g.user["rol"])

    view.__name__ = f"module_{slug.replace('-', '_')}"
    return view


for _slug in mr.MODULES:
    bp.add_url_rule(
        f"/{_slug}" if _slug != "dashboard" else "/dashboard",
        endpoint=_slug.replace("-", "_"),
        view_func=_route(_slug),
        methods=["GET", "POST"],
    )


@bp.route("/")
def index():
    return redirect(url_for("modules.dashboard"))


def _safe_back_url(raw: str | None) -> str:
    if not raw:
        return url_for("modules.dashboard")
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    try:
        parsed = urlparse(raw)
        if parsed.netloc and parsed.netloc != request.host:
            return url_for("modules.dashboard")
        return raw
    except Exception:
        return url_for("modules.dashboard")


@bp.route("/pdf/view/<token>")
@login_required
def pdf_view(token: str):
    got = mr.get_pdf(token)
    if not got:
        return Response("PDF no encontrado o expirado.", status=404)
    _, filename = got
    back_url = _safe_back_url(request.args.get("back") or request.referrer)
    pdf_embed_url = url_for("modules.pdf_download", token=token, inline=1)
    pdf_share_url = url_for("modules.pdf_download", token=token)
    return render_template(
        "pdf_viewer.html",
        page_title=f"PDF — {filename}",
        filename=filename,
        back_url=back_url,
        pdf_embed_url=pdf_embed_url,
        pdf_share_url=pdf_share_url,
    )


@bp.route("/pdf/<token>")
@login_required
def pdf_download(token: str):
    got = mr.get_pdf(token)
    if not got:
        return Response("PDF no encontrado o expirado.", status=404)
    blob, filename = got
    inline = request.args.get("inline") in ("1", "true", "yes")
    disposition = "inline" if inline else "attachment"
    return Response(
        blob,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@bp.route("/fitosanitarios/<especie>/pdf")
@login_required
@module_required("Libro de Campo")
def fitosanitario_pdf(especie: str):
    from demo_web.services.native.libro_campo import FITOSANITARIO_PROGRAMAS, ruta_programa_pdf

    meta = FITOSANITARIO_PROGRAMAS.get(especie)
    path = ruta_programa_pdf(especie)
    if not meta or not path:
        abort(404)
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=meta["descarga"],
        max_age=3600,
    )


@bp.route("/fitosanitarios/<especie>/pagina/<int:n>")
@login_required
@module_required("Libro de Campo")
def fitosanitario_pagina(especie: str, n: int):
    from demo_web.services.native.libro_campo import FITOSANITARIO_PROGRAMAS, ruta_programa_pagina

    if especie not in FITOSANITARIO_PROGRAMAS:
        abort(404)
    path = ruta_programa_pagina(especie, n)
    if not path:
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=3600)
