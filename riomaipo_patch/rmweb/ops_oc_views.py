"""Rutas Flask: Órdenes de compra (bajo sección Compras)."""
from __future__ import annotations

from datetime import date

from flask import flash, redirect, render_template, request, url_for

from rmweb import core
from rmweb import ops
from rmweb import ops_oc


def register_oc_routes(app, login_required):
    @app.context_processor
    def _oc_inject():
        return {
            "oc_estado_class": ops_oc.oc_estado_class,
            "oc_estado_label": ops_oc.oc_estado_label,
        }

    @app.route("/compras/ordenes/")
    @login_required
    def oc_list():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        rows = db.execute(
            """
            SELECT o.*, p.razon_social AS proveedor
            FROM ordenes_compra o
            LEFT JOIN proveedores p ON p.id=o.proveedor_id
            ORDER BY COALESCE(o.fecha,'') DESC, o.id DESC
            """
        ).fetchall()
        kpis = ops_oc.kpis_oc(db)
        db.close()
        return render_template(
            "ordenes/lista.html", active="ordenes", rows=rows, kpis=kpis
        )

    @app.route("/compras/ordenes/nueva", methods=["GET", "POST"])
    @app.route("/compras/ordenes/<int:oid>/editar", methods=["GET", "POST"])
    @login_required
    def oc_form(oid: int | None = None):
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        row = (
            db.execute("SELECT * FROM ordenes_compra WHERE id=?", (oid,)).fetchone()
            if oid
            else None
        )
        if row and (row["estado"] or "") in ("convertida", "anulada"):
            db.close()
            flash("Esta OC no se puede editar", "danger")
            return redirect(url_for("oc_detalle", oid=oid))

        items = []
        if row:
            items = db.execute(
                "SELECT * FROM orden_compra_items WHERE orden_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
        proveedores = db.execute(
            "SELECT id, razon_social FROM proveedores WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        productos = db.execute(
            """
            SELECT id, codigo, nombre, unidad, precio, COALESCE(es_servicio,0) AS es_servicio
            FROM productos WHERE activo=1 ORDER BY nombre
            """
        ).fetchall()

        if request.method == "POST":
            try:
                proveedor_id = int(request.form.get("proveedor_id") or 0)
            except ValueError:
                proveedor_id = 0
            concepto = (request.form.get("concepto") or "").strip()
            fe = (request.form.get("fecha") or date.today().isoformat()).strip()
            fent = (request.form.get("fecha_entrega") or "").strip() or None
            notas = (request.form.get("notas") or "").strip()
            accion = (request.form.get("accion") or "guardar").strip()
            lineas, neto = ops_oc.parse_oc_lineas(request.form, productos)
            pct = ops_oc.iva_pct(db)
            iva = round(neto * pct / 100.0, 2)
            total = round(neto + iva, 2)
            estado = "emitida" if accion == "emitir" else (row["estado"] if row else "borrador")
            if estado not in ("borrador", "emitida"):
                estado = "borrador"
            if accion == "emitir":
                estado = "emitida"

            if not proveedor_id:
                flash("Seleccione proveedor", "danger")
            elif not lineas:
                flash("Agregue al menos un ítem", "danger")
            else:
                try:
                    if row:
                        db.execute(
                            """
                            UPDATE ordenes_compra SET proveedor_id=?, concepto=?, fecha=?,
                            fecha_entrega=?, neto=?, iva=?, total=?, estado=?, notas=?
                            WHERE id=?
                            """,
                            (
                                proveedor_id,
                                concepto,
                                fe,
                                fent,
                                neto,
                                iva,
                                total,
                                estado,
                                notas,
                                row["id"],
                            ),
                        )
                        oid_use = int(row["id"])
                    else:
                        folio = ops_oc.next_oc_folio(db)
                        cur = db.execute(
                            """
                            INSERT INTO ordenes_compra
                            (folio, proveedor_id, concepto, fecha, fecha_entrega,
                             neto, iva, total, estado, notas, creado_en)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                folio,
                                proveedor_id,
                                concepto,
                                fe,
                                fent,
                                neto,
                                iva,
                                total,
                                estado,
                                notas,
                                date.today().isoformat(),
                            ),
                        )
                        oid_use = int(cur.lastrowid)
                    ops_oc.save_oc_items(db, oid_use, lineas)
                    db.commit()
                    flash(
                        "Orden emitida" if estado == "emitida" else "Orden guardada",
                        "ok",
                    )
                    db.close()
                    return redirect(url_for("oc_detalle", oid=oid_use))
                except Exception as exc:
                    db.rollback()
                    flash(f"No se pudo guardar: {exc}", "danger")

        db.close()
        return render_template(
            "ordenes/form.html",
            active="ordenes",
            row=row,
            items=items,
            proveedores=proveedores,
            productos=productos,
            hoy=date.today().isoformat(),
        )

    @app.route("/compras/ordenes/<int:oid>")
    @login_required
    def oc_detalle(oid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        row = db.execute(
            """
            SELECT o.*, p.razon_social AS proveedor
            FROM ordenes_compra o
            LEFT JOIN proveedores p ON p.id=o.proveedor_id
            WHERE o.id=?
            """,
            (oid,),
        ).fetchone()
        if not row:
            db.close()
            flash("Orden no encontrada", "danger")
            return redirect(url_for("oc_list"))
        items = db.execute(
            "SELECT * FROM orden_compra_items WHERE orden_id=? ORDER BY id",
            (oid,),
        ).fetchall()
        db.close()
        return render_template(
            "ordenes/detalle.html", active="ordenes", row=row, items=items
        )

    @app.route("/compras/ordenes/<int:oid>/estado", methods=["POST"])
    @login_required
    def oc_estado(oid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        nuevo = (request.form.get("estado") or "").strip().lower()
        row = db.execute("SELECT * FROM ordenes_compra WHERE id=?", (oid,)).fetchone()
        if not row:
            db.close()
            flash("Orden no encontrada", "danger")
            return redirect(url_for("oc_list"))
        actual = (row["estado"] or "").lower()
        if actual in ("convertida", "anulada"):
            db.close()
            flash("Estado no modificable", "danger")
            return redirect(url_for("oc_detalle", oid=oid))
        if nuevo == "emitida" and actual == "borrador":
            db.execute("UPDATE ordenes_compra SET estado='emitida' WHERE id=?", (oid,))
            db.commit()
            flash("OC emitida", "ok")
        elif nuevo == "anulada" and actual in ("borrador", "emitida"):
            db.execute("UPDATE ordenes_compra SET estado='anulada' WHERE id=?", (oid,))
            db.commit()
            flash("OC anulada", "ok")
        else:
            flash("Cambio de estado no permitido", "danger")
        db.close()
        return redirect(url_for("oc_detalle", oid=oid))

    @app.route("/compras/ordenes/<int:oid>/convertir", methods=["GET", "POST"])
    @login_required
    def oc_convertir(oid: int):
        # Compat: emitir compra = formulario de compra linkeado a la OC
        return redirect(url_for("compras_form", oc=oid))
