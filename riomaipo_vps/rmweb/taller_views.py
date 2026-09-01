"""Módulo Taller — órdenes de trabajo (OT)."""
from __future__ import annotations

from flask import flash, redirect, render_template, session, url_for

from rmweb.tenants import modulo_visible


def register_taller_routes(app, login_required):
    @app.route("/taller/")
    @login_required
    def taller_ot_list():
        slug = (session.get("tenant_slug") or "").strip().lower()
        if not modulo_visible(slug, "taller_ot"):
            flash("Este módulo no está disponible en su tenant.", "warning")
            return redirect(url_for("dashboard"))

        return render_template(
            "taller/lista.html",
            active="taller_ot",
            rows=[],
        )
