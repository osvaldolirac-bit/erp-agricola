"""Vista móvil: stock bodega LC + kardex por producto (acceso directo / pantalla inicio)."""
from __future__ import annotations

from flask import abort, render_template, request, url_for

from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app


def _parse_pid() -> int:
    raw = (request.args.get("pid") or "0").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def view(user_email: str, user_rol: str):
    if get_erp_app() != "concepcion":
        abort(404)
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    if demo.es_certificacion():
        abort(404)

    q = (request.args.get("q") or "").strip()
    pid = _parse_pid()

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

        kardex_ctx: dict = {}
        if pid:
            from demo_web.services import bodega_kardex

            kardex_ctx = bodega_kardex.gather_kardex_producto(demo, conn, pid)
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

    return render_template(
        "stock_bodega_rapido.html",
        page_title=page_title,
        items=items,
        filtro_q=q,
        pid=pid,
        kardex_error=kardex_ctx.get("kardex_error"),
        kardex_producto=kardex_ctx.get("kardex_producto"),
        kardex_rows=kardex_ctx.get("kardex_rows") or [],
        kardex_lc_pendientes=kardex_ctx.get("kardex_lc_pendientes") or [],
        url_stock_list=url_for("modules.stock_bodega_rapido", q=q or None),
        actualizado=demo.hora_chile().strftime("%d-%m-%Y %H:%M"),
        erp_title=getattr(demo, "NOMBRE_ERP", "La Concepción"),
    )
