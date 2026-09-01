"""Módulo Taller — órdenes de trabajo (OT)."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for

from rmweb import core
from rmweb import ops_taller
from rmweb.tenants import modulo_visible


def register_taller_routes(app, login_required):
    @app.route("/taller/")
    @login_required
    def taller_ot_list():
        slug = (session.get("tenant_slug") or "").strip().lower()
        if not modulo_visible(slug, "taller_ot"):
            flash("Este módulo no está disponible en su tenant.", "warning")
            return redirect(url_for("dashboard"))

        db = core.conn()
        ops_taller.ensure_taller_schema(db)
        rows = db.execute(
            """
            SELECT ot.*, cl.razon_social AS cliente, cot.folio AS cot_folio, cot.total AS cot_total
            FROM taller_ordenes ot
            LEFT JOIN clientes cl ON cl.id=ot.cliente_id
            LEFT JOIN cotizaciones cot ON cot.id=ot.cotizacion_id
            ORDER BY ot.id DESC
            """
        ).fetchall()
        db.close()
        return render_template(
            "taller/lista.html",
            active="taller_ot",
            rows=rows,
            estado_label=ops_taller.estado_ot_label,
        )

    @app.route("/taller/<int:ot_id>", methods=["GET", "POST"])
    @login_required
    def taller_ot_detalle(ot_id: int):
        slug = (session.get("tenant_slug") or "").strip().lower()
        if not modulo_visible(slug, "taller_ot"):
            flash("Este módulo no está disponible en su tenant.", "warning")
            return redirect(url_for("dashboard"))

        db = core.conn()
        ops_taller.ensure_taller_schema(db)
        row = db.execute(
            """
            SELECT ot.*, cl.razon_social AS cliente, cl.rut AS cliente_rut,
                   cot.folio AS cot_folio, cot.total AS cot_total, cot.asunto AS cot_asunto
            FROM taller_ordenes ot
            LEFT JOIN clientes cl ON cl.id=ot.cliente_id
            LEFT JOIN cotizaciones cot ON cot.id=ot.cotizacion_id
            WHERE ot.id=?
            """,
            (ot_id,),
        ).fetchone()
        if not row:
            db.close()
            flash("OT no encontrada", "danger")
            return redirect(url_for("taller_ot_list"))

        if request.method == "POST":
            ok, msg = ops_taller.actualizar_ot(
                db,
                ot_id,
                mecanico=request.form.get("mecanico"),
                estado=request.form.get("estado") or "pendiente",
                notas=request.form.get("notas"),
            )
            if ok:
                db.commit()
                flash(msg, "ok")
            else:
                flash(msg, "danger")
            db.close()
            return redirect(url_for("taller_ot_detalle", ot_id=ot_id))

        items = []
        if row["cotizacion_id"]:
            items = db.execute(
                """
                SELECT descripcion, obs, unidad, cantidad, precio_unitario, total
                FROM cotizacion_items
                WHERE cotizacion_id=?
                ORDER BY COALESCE(orden,0), id
                """,
                (row["cotizacion_id"],),
            ).fetchall()
            items = [
                it
                for it in items
                if not core._is_gg_line(it["descripcion"])
                and not core._is_util_line(it["descripcion"])
            ]
        db.close()
        return render_template(
            "taller/detalle.html",
            active="taller_ot",
            row=row,
            items=items,
            estados=ops_taller.ESTADOS_OT,
            estado_label=ops_taller.estado_ot_label,
        )
