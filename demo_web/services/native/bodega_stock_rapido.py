"""Vista móvil: stock bodega LC + kardex por producto (ERP o link con token)."""
from __future__ import annotations

import pandas as pd
from flask import abort, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app
from demo_web.services.module_runner import store_pdf


def _parse_pid() -> int:
    raw = (request.args.get("pid") or "0").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _pdf_stock_operativo(
    demo,
    conn,
    *,
    link_tok: str | None,
) -> tuple[str | None, str | None]:
    """PDF listado stock completo (todos los productos con stock > 0)."""
    dfs = pd.read_sql_query(
        """SELECT producto, familia, stock, COALESCE(unidad_medida, 'kg') AS unidad_medida,
                  COALESCE(ingrediente_activo,'') AS ingrediente_activo, pppl_aprobado
           FROM inventario
           WHERE COALESCE(stock, 0) > 0
           ORDER BY producto COLLATE NOCASE""",
        conn,
    )
    if dfs.empty:
        return None, None

    dfs_op = dfs.rename(
        columns={"unidad_medida": "UM", "ingrediente_activo": "ING. ACTIVO"},
    )
    if "pppl_aprobado" in dfs_op.columns:
        dfs_op = dfs_op.rename(columns={"pppl_aprobado": "PPPL"})
        dfs_op["PPPL"] = dfs_op["PPPL"].apply(lambda v: int(bool(v)))

    estilo = getattr(demo, "_pdf_estilo_stock_pppl", None)
    blob = demo.generar_pdf_blob(
        dfs_op,
        f"STOCK ACTUAL COMPLETO — {len(dfs_op)} productos",
        incluir_precios=False,
        estilo_celda_fn=estilo,
    )
    if not blob:
        return None, None

    fname = "STOCK_BODEGA_MOVIL.pdf"
    token = store_pdf(blob, fname)
    if link_tok:
        view_url = url_for(
            "stock_bodega_link.visor_pdf",
            token=token,
            download_name=fname,
            t=link_tok,
            titulo="Stock bodega completo",
        )
    else:
        back = url_for("modules.stock_bodega_rapido", q=q or None)
        view_url = url_for(
            "modules.pdf_view",
            token=token,
            download_name=fname,
            back=back,
        )
    return view_url, fname


def _make_pdf_link_factory(
    *,
    link_tok: str | None,
    q: str,
    pid: int,
    product_name: str | None = None,
):
    if link_tok:

        def _factory(token, fname):  # noqa: ANN001
            titulo = (product_name or "").strip() or "Cuenta corriente bodega"
            return url_for(
                "stock_bodega_link.visor_pdf",
                token=token,
                download_name=fname,
                t=link_tok,
                pid=pid or None,
                q=q or None,
                titulo=titulo,
            )

        return _factory

    def _factory(token, fname):  # noqa: ANN001
        back = url_for("modules.stock_bodega_rapido", pid=pid or None, q=q or None)
        return url_for(
            "modules.pdf_view",
            token=token,
            download_name=fname,
            back=back,
        )

    return _factory


def _build_context(demo, *, link_tok: str | None, q: str, pid: int) -> dict:
    conn = demo.conectar_db()
    try:
        rows = conn.execute(
            """SELECT id, producto, COALESCE(stock, 0) AS stock,
                      COALESCE(unidad_medida, ?) AS um,
                      COALESCE(familia, '') AS familia
               FROM inventario
               WHERE stock > 0
               ORDER BY producto COLLATE NOCASE""",
            (demo.DEFAULT_UNIDAD_INSUMO,),
        ).fetchall()

        product_name = None
        if pid:
            prow = conn.execute(
                "SELECT producto FROM inventario WHERE id=?", (pid,)
            ).fetchone()
            if prow:
                product_name = str(prow[0] or "")

        pdf_link_factory = _make_pdf_link_factory(
            link_tok=link_tok,
            q=q,
            pid=pid,
            product_name=product_name,
        )

        kardex_ctx: dict = {}
        if pid:
            from demo_web.services import bodega_kardex

            kardex_ctx = bodega_kardex.gather_kardex_producto(
                demo,
                conn,
                pid,
                include_pdf=True,
                pdf_link_factory=pdf_link_factory,
            )

        pdf_stock_url, pdf_stock_filename = (None, None)
        if not pid:
            pdf_stock_url, pdf_stock_filename = _pdf_stock_operativo(
                demo, conn, link_tok=link_tok
            )
    finally:
        conn.close()

    items = []
    ql = q.lower()
    for r in rows:
        iid = int(r[0])
        prod = str(r[1] or "")
        stock_f = float(r[2] or 0)
        um = str(r[3] or "")
        fam = str(r[4] or "")
        if q and ql not in prod.lower() and ql not in fam.lower():
            continue
        items.append(
            {
                "id": iid,
                "producto": prod,
                "stock": demo.f_cantidad(stock_f),
                "um": um,
                "familia": fam,
                "activo": pid == iid,
            }
        )

    page_title = "Stock bodega"
    if kardex_ctx.get("kardex_producto"):
        page_title = kardex_ctx["kardex_producto"]["nombre"]

    if link_tok:
        url_stock_list = url_for(
            "stock_bodega_link.formulario",
            t=link_tok,
            q=q or None,
        )
        link_mode = True
    else:
        url_stock_list = url_for("modules.stock_bodega_rapido", q=q or None)
        link_mode = False

    return {
        "page_title": page_title,
        "items": items,
        "filtro_q": q,
        "pid": pid,
        "kardex_error": kardex_ctx.get("kardex_error"),
        "kardex_producto": kardex_ctx.get("kardex_producto"),
        "kardex_rows": kardex_ctx.get("kardex_rows") or [],
        "kardex_lc_pendientes": kardex_ctx.get("kardex_lc_pendientes") or [],
        "pdf_url": (
            kardex_ctx.get("pdf_kardex_url")
            if pid
            else pdf_stock_url
        ),
        "pdf_button_label": (
            "Ver PDF cuenta corriente"
            if pid
            else "Ver PDF stock completo"
        ),
        "url_stock_list": url_stock_list,
        "link_tok": link_tok,
        "link_mode": link_mode,
        "actualizado": demo.hora_chile().strftime("%d-%m-%Y %H:%M"),
        "erp_title": getattr(demo, "NOMBRE_ERP", "La Concepción"),
    }


def render_public(link_tok: str):
    demo = get_demo_module()
    if demo.es_certificacion():
        abort(404)
    q = (request.args.get("q") or "").strip()
    pid = _parse_pid()
    ctx = _build_context(demo, link_tok=link_tok, q=q, pid=pid)
    return render_template("stock_bodega_rapido.html", **ctx)


def view(user_email: str, user_rol: str):
    if get_erp_app() != "concepcion":
        abort(404)
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    if demo.es_certificacion():
        abort(404)

    q = (request.args.get("q") or "").strip()
    pid = _parse_pid()
    ctx = _build_context(demo, link_tok=None, q=q, pid=pid)
    return render_template("stock_bodega_rapido.html", **ctx)
