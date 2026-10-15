"""Vista móvil: stock bodega LC solo lectura (acceso directo / pantalla inicio)."""
from __future__ import annotations

from flask import abort, render_template, request

from demo_web.services.demo_loader import bind_user_session, get_demo_module, get_erp_app


def view(user_email: str, user_rol: str):
    if get_erp_app() != "concepcion":
        abort(404)
    demo = get_demo_module()
    bind_user_session(user_email, user_rol)
    if demo.es_certificacion():
        abort(404)

    q = (request.args.get("q") or "").strip()
    conn = demo.conectar_db()
    try:
        rows = conn.execute(
            """SELECT producto, COALESCE(stock, 0) AS stock,
                      COALESCE(unidad_medida, ?) AS um,
                      COALESCE(familia, '') AS familia
               FROM inventario
               WHERE stock > 0
               ORDER BY producto COLLATE NOCASE""",
            (demo.DEFAULT_UNIDAD_INSUMO,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    ql = q.lower()
    for r in rows:
        prod = str(r[0] or "")
        fam = str(r[3] or "")
        if q and ql not in prod.lower() and ql not in fam.lower():
            continue
        items.append(
            {
                "producto": prod,
                "stock": demo.f_cantidad(float(r[1] or 0)),
                "um": str(r[2] or ""),
                "familia": fam,
            }
        )

    return render_template(
        "stock_bodega_rapido.html",
        page_title="Stock bodega",
        items=items,
        filtro_q=q,
        actualizado=demo.hora_chile().strftime("%d-%m-%Y %H:%M"),
        erp_title=getattr(demo, "NOMBRE_ERP", "La Concepción"),
    )
