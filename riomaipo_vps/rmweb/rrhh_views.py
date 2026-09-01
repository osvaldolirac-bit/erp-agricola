"""Vistas RRHH — sueldos imputados a centros de costo."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for

from rmweb import core
from rmweb import ops_rrhh


def register_rrhh_routes(app, login_required):
    @app.route("/rrhh/", methods=["GET", "POST"])
    @login_required
    def rrhh_home():
        db = core.conn()
        ops_rrhh.ensure_rrhh_schema(db)
        hoy = core.hoy_chile()

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "trabajador":
                ok, msg = ops_rrhh.crear_trabajador(
                    db,
                    nombre=request.form.get("nombre"),
                    rut=request.form.get("rut"),
                    cargo=request.form.get("cargo"),
                )
                if ok:
                    db.commit()
                    flash(msg, "ok")
                else:
                    flash(msg, "danger")
                db.close()
                return redirect(url_for("rrhh_home"))

            if action == "imputar":
                try:
                    tid = int(request.form.get("trabajador_id") or 0)
                    mes = int(request.form.get("mes") or hoy.month)
                    anio = int(request.form.get("anio") or hoy.year)
                except (TypeError, ValueError):
                    flash("Datos de imputación inválidos.", "danger")
                    db.close()
                    return redirect(url_for("rrhh_home"))
                ok, msg, _pid = ops_rrhh.registrar_pago(
                    db,
                    trabajador_id=tid,
                    mes=mes,
                    anio=anio,
                    liquido=request.form.get("liquido"),
                    leyes=request.form.get("leyes"),
                    nota=request.form.get("nota"),
                )
                if ok:
                    db.commit()
                    flash(msg, "ok")
                else:
                    flash(msg, "danger")
                db.close()
                return redirect(url_for("rrhh_home"))

        trabajadores = ops_rrhh.list_trabajadores(db, solo_activos=False)
        pagos = ops_rrhh.list_pagos(db)
        reparto = ops_rrhh.resumen_cc_activos(db)
        db.close()
        return render_template(
            "rrhh/home.html",
            active="rrhh",
            trabajadores=trabajadores,
            pagos=pagos,
            reparto=reparto,
            meses=ops_rrhh.MESES,
            mes_actual=hoy.month,
            anio_actual=hoy.year,
            mes_label=ops_rrhh.mes_label,
        )
