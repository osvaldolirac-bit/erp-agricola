"""Rutas Flask del módulo Constructora."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for

from rmweb import constructora as cst
from rmweb import core
from rmweb import obra_contrato as obractx


def register_constructora_routes(app, login_required):
    @app.route("/hub/")
    @login_required
    def constructora_home():
        return redirect(url_for("constructora_obras"))


    @app.route("/obra")
    @app.route("/obra/")
    @login_required
    def constructora_obra_alias():
        return redirect(url_for("constructora_obras"))

    # ── Obras (1 obra = 1 CC) ─────────────────────────────────────
    @app.route("/obras/")
    @login_required
    def constructora_obras():
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        obras = cst.list_obras(db)
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        obras_view = []
        ppto_total = 0.0
        avance_sum = 0.0
        n_activas = 0
        for o in obras:
            av = obractx.resumen_avance_obra(db, int(o["id"]))
            ppto = float(av.get("ppto") or o["presupuesto"] or 0)
            pct = float(av.get("avance_pct_pond") or 0)
            ppto_total += ppto
            avance_sum += pct
            if int(o["activo"] or 0) and (o["estado_obra"] or "activa") == "activa":
                n_activas += 1
            obras_view.append(
                {
                    "id": int(o["id"]),
                    "nombre": o["nombre"],
                    "cliente_nombre": o["cliente_nombre"],
                    "estado_obra": o["estado_obra"] or "activa",
                    "fecha_inicio": o["fecha_inicio"],
                    "activo": int(o["activo"] or 0),
                    "ppto": ppto,
                    "avance_pct": pct,
                    "avanzado_clp": float(av.get("avanzado_clp") or 0),
                    "cot_estado": (o["cotizacion_obra_estado"] if "cotizacion_obra_estado" in o.keys() else None)
                    or ("aprobada" if av.get("aprobada") else "borrador"),
                }
            )
        n = len(obras_view) or 1
        db.close()
        return render_template(
            "constructora/obras.html",
            active="constructora",
            obras=obras,
            obras_view=obras_view,
            clientes=clientes,
            hoy=core.hoy_chile().isoformat(),
            n_activas=n_activas,
            ppto_total=ppto_total,
            avance_medio=avance_sum / n if obras_view else 0.0,
        )

    @app.route("/obras/nueva", methods=["POST"])
    @login_required
    def constructora_obra_nueva():
        db = core.conn()
        cst.ensure_constructora_schema(db)
        try:
            cli = int(request.form.get("cliente_id") or 0) or None
        except ValueError:
            cli = None
        ok, msg, _oid = cst.crear_obra(
            db,
            nombre=request.form.get("nombre") or "",
            cliente_id=cli,
            presupuesto=0,
            fecha_inicio=request.form.get("fecha_inicio") or None,
            notas_estado=request.form.get("estado_obra") or "activa",
        )
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        if ok and _oid:
            return redirect(url_for("constructora_obra_detalle", obra_id=int(_oid), sec="cotizacion"))
        return redirect(url_for("constructora_obras"))

    @app.route("/obras/<int:obra_id>", methods=["GET", "POST"])
    @login_required
    def constructora_obra_detalle(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        sec = (request.args.get("sec") or request.form.get("sec") or "cotizacion").strip().lower()
        if sec not in ("cotizacion", "apu", "gantt", "eepp", "datos", "subcontratos"):
            sec = "cotizacion"

        if request.method == "POST" and sec == "datos":
            try:
                cli = int(request.form.get("cliente_id") or 0) or None
            except ValueError:
                cli = None
            ok, msg = cst.actualizar_obra(
                db,
                obra_id,
                nombre=request.form.get("nombre"),
                activo=1 if request.form.get("activo") == "1" else 0,
                cliente_id=cli,
                estado_obra=request.form.get("estado_obra"),
                fecha_inicio=request.form.get("fecha_inicio"),
                fecha_fin=request.form.get("fecha_fin"),
                presupuesto=None,
            )
            if ok:
                db.commit()
                flash(msg, "ok")
            else:
                db.rollback()
                flash(msg, "danger")
            db.close()
            return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="datos"))

        resumen = cst.obra_resumen(db, obra_id)
        if not resumen:
            flash("Obra no encontrada.", "danger")
            db.close()
            return redirect(url_for("constructora_obras"))
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        partidas = obractx.list_partidas(db, obra_id)
        eepps = obractx.list_eepp(db, obra_id)
        avance = obractx.resumen_avance_obra(db, obra_id)
        ppto_totales = obractx.totales_cotizacion_obra(db, obra_id)
        sugerido_capitulo = obractx.next_partida_codigo(db, obra_id, "capitulo")
        sugerido_partida = obractx.next_partida_codigo(db, obra_id, "partida")
        try:
            from rmweb import subcontratos as _sc
            _sc.ensure_subcontratos_schema(db)
            subs_obra = _sc.list_subcontratos_enriquecidos(db, obra_id=obra_id)
            subs_resumen = _sc.resumen_subcontratos_obra(db, obra_id)
        except Exception:
            subs_obra, subs_resumen = [], {'n':0,'monto_contrato':0,'monto_pagado':0,'saldo':0}
        db.close()
        return render_template(
            "constructora/obra_detalle.html",
            active="constructora",
            resumen=resumen,
            obra=resumen["obra"],
            clientes=clientes,
            partidas=partidas,
            eepps=eepps,
            avance=avance,
            sec=sec,
            subcontratos=subs_obra,
            subs_resumen=subs_resumen,
            ppto_totales=ppto_totales,
            marca_labels=obractx.MARCA_LABELS,
            partidas_gantt=[p for p in partidas if obractx.linea_requiere_apu(p)],
            sugerido_capitulo=sugerido_capitulo,
            sugerido_partida=sugerido_partida,
        )

    @app.route("/obras/<int:obra_id>/partidas/nueva", methods=["POST"])
    @login_required
    def constructora_obra_partida_nueva(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        ok, msg, _pid = obractx.guardar_partida(
            db,
            obra_id=obra_id,
            partida_id=None,
            codigo=request.form.get("codigo") or "",
            detalle=request.form.get("detalle") or "",
            unidad=request.form.get("unidad") or "gl",
            cantidad=request.form.get("cantidad") or 1,
            notas=request.form.get("notas") or "",
            tipo_linea=request.form.get("tipo_linea") or "partida",
            marca=request.form.get("marca") or "",
        )
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))

    @app.route("/obras/<int:obra_id>/partidas/<int:partida_id>/eliminar", methods=["POST"])
    @login_required
    def constructora_obra_partida_eliminar(obra_id: int, partida_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        ok, msg = obractx.eliminar_partida(db, obra_id, partida_id)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))

    @app.route("/obras/<int:obra_id>/partidas/renumerar", methods=["POST"])
    @login_required
    def constructora_obra_partidas_renumerar(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        ok, msg, _n = obractx.renumerar_codigos_itemizados(db, obra_id)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))

    @app.route("/obras/<int:obra_id>/presupuesto/params", methods=["POST"])
    @login_required
    def constructora_obra_ppto_params(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        ok, msg = obractx.guardar_parametros_presupuesto(
            db,
            obra_id,
            ubicacion=request.form.get("ubicacion") or "",
            propietario=request.form.get("propietario") or "",
            documento_cot=request.form.get("documento_cot") or "",
            duracion_meses=request.form.get("duracion_meses") or 0,
            gg_pct=request.form.get("gg_pct") or 0,
            utilidades_pct=request.form.get("utilidades_pct") or 0,
            descuento_clp=request.form.get("descuento_clp") or 0,
            iva_pct=request.form.get("iva_pct") or 19,
            valor_uf=request.form.get("valor_uf") or 0,
        )
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))

    @app.route("/obras/<int:obra_id>/partidas/<int:partida_id>/editar", methods=["POST"])
    @login_required
    def constructora_obra_partida_editar(obra_id: int, partida_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        ok, msg, _ = obractx.guardar_partida(
            db,
            obra_id=obra_id,
            partida_id=partida_id,
            codigo=request.form.get("codigo") or "",
            detalle=request.form.get("detalle") or "",
            unidad=request.form.get("unidad") or "gl",
            cantidad=request.form.get("cantidad") or 0,
            notas=request.form.get("notas") or "",
            tipo_linea=request.form.get("tipo_linea") or "partida",
            marca=request.form.get("marca") or "",
        )
        if ok:
            # Re-sync total from APU if linked
            row = obractx.get_partida(db, partida_id, obra_id)
            if row and row["apu_id"]:
                obractx.sync_partida_desde_apu(db, int(row["apu_id"]))
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))

    @app.route("/obras/<int:obra_id>/aprobar", methods=["POST"])
    @login_required
    def constructora_obra_aprobar(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        ok, msg = obractx.aprobar_cotizacion_obra(db, obra_id)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))


    @app.route("/obras/<int:obra_id>/reabrir", methods=["POST"])
    @login_required
    def constructora_obra_reabrir(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        ok, msg = obractx.reabrir_cotizacion_obra(db, obra_id)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="cotizacion"))


    @app.route("/obras/<int:obra_id>/gantt", methods=["POST"])
    @login_required
    def constructora_obra_gantt(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        pids = request.form.getlist("partida_id")
        pcts = request.form.getlist("avance_pct")
        avances = []
        for i, raw in enumerate(pids):
            avances.append(
                {
                    "partida_id": raw,
                    "avance_pct": pcts[i] if i < len(pcts) else 0,
                }
            )
        ok, msg = obractx.guardar_avances_gantt(db, obra_id, avances)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="gantt"))


    @app.route("/obras/<int:obra_id>/subcontratos/avances", methods=["POST"])
    @login_required
    def constructora_obra_subcontratos_avances(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        from rmweb import subcontratos as _sc
        _sc.ensure_subcontratos_schema(db)
        sids = request.form.getlist("subcontrato_id")
        pcts = request.form.getlist("avance_trabajos_pct")
        avances = []
        for i, raw in enumerate(sids):
            avances.append(
                {
                    "subcontrato_id": raw,
                    "avance_trabajos_pct": pcts[i] if i < len(pcts) else 0,
                }
            )
        ok, msg = _sc.guardar_avances_trabajos(db, obra_id, avances)
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="subcontratos"))


    @app.route("/obras/<int:obra_id>/eepp/nuevo", methods=["POST"])
    @login_required
    def constructora_obra_eepp_nuevo(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        ok, msg, eid = obractx.generar_eepp_desde_gantt(
            db, obra_id, notas=request.form.get("notas") or ""
        )
        if ok:
            db.commit()
            flash(msg, "ok")
            db.close()
            if eid:
                return redirect(
                    url_for("constructora_obra_eepp_detalle", obra_id=obra_id, eepp_id=eid)
                )
        else:
            db.rollback()
            flash(msg, "danger")
            db.close()
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="eepp"))

    @app.route("/obras/<int:obra_id>/eepp/<int:eepp_id>")
    @login_required
    def constructora_obra_eepp_detalle(obra_id: int, eepp_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        det = obractx.eepp_detalle(db, eepp_id, obra_id)
        obra = db.execute(
            "SELECT * FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
            (obra_id,),
        ).fetchone()
        db.close()
        if not det or not obra:
            flash("EEPP no encontrado.", "danger")
            return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="eepp"))
        return render_template(
            "constructora/eepp_detalle.html",
            active="constructora",
            obra=obra,
            eepp=det["eepp"],
            items=det["items"],
        )


    # ── APU por obra ──────────────────────────────────────────────
    @app.route("/apu/")
    @login_required
    def constructora_apu_list():
        """Legacy: APU ya no es global; ir a Obras."""
        flash("El APU se gestiona dentro de cada obra.", "ok")
        return redirect(url_for("constructora_obras"))

    @app.route("/apu/nuevo", methods=["GET", "POST"])
    @app.route("/apu/<int:apu_id>", methods=["GET", "POST"])
    @login_required
    def constructora_apu_form_legacy(apu_id: int | None = None):
        flash("Abra el APU desde la obra correspondiente.", "ok")
        return redirect(url_for("constructora_obras"))

    @app.route("/obras/<int:obra_id>/apu/")
    @login_required
    def constructora_obra_apu_list(obra_id: int):
        return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="apu"))

    @app.route("/obras/<int:obra_id>/apu/nuevo", methods=["GET", "POST"])
    @app.route("/obras/<int:obra_id>/apu/<int:apu_id>", methods=["GET", "POST"])
    @login_required
    def constructora_apu_form(obra_id: int, apu_id: int | None = None):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obractx.ensure_obra_contrato_schema(db)
        obra = db.execute(
            "SELECT * FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
            (obra_id,),
        ).fetchone()
        if not obra:
            flash("Obra no encontrada.", "danger")
            db.close()
            return redirect(url_for("constructora_obras"))

        edit = cst.get_apu_de_obra(db, apu_id, obra_id) if apu_id else None
        if apu_id and not edit:
            flash("APU no encontrado en esta obra.", "danger")
            db.close()
            return redirect(url_for("constructora_obra_detalle", obra_id=obra_id, sec="apu"))
        try:
            partida_id = int(request.args.get("partida") or request.form.get("partida_id") or 0) or None
        except ValueError:
            partida_id = None
        if edit and edit["partida_id"] and not partida_id:
            partida_id = int(edit["partida_id"])
        partida = obractx.get_partida(db, partida_id, obra_id) if partida_id else None
        congelado = bool(edit and int(edit["congelado"] or 0)) or obractx.obra_cotizacion_aprobada(db, obra_id)
        items = cst.list_apu_items(db, apu_id) if apu_id else []
        precios = cst.list_precios_obra(db, solo_activos=True)

        if request.method == "POST" and request.form.get("action") == "recalcular":
            if not apu_id:
                flash("Guarde el APU antes de recalcular.", "danger")
            else:
                ok, msg = cst.recalcular_apu_desde_maestra(db, apu_id)
                if ok:
                    db.commit()
                    flash(msg, "ok")
                else:
                    db.rollback()
                    flash(msg, "danger")
            db.close()
            return redirect(
                url_for("constructora_apu_form", obra_id=obra_id, apu_id=apu_id)
            )

        if request.method == "POST" and congelado:
            flash("APU / cotización congelada: solo lectura.", "danger")
            db.close()
            return redirect(
                url_for("constructora_obra_detalle", obra_id=obra_id, sec="apu")
            )

        if request.method == "POST":
            pids = request.form.getlist("item_producto_id")
            cants = request.form.getlist("item_cant")
            # ítems con PU editable (foto)
            pus = request.form.getlist("item_pu")
            tipos = request.form.getlist("item_tipo")
            unds = request.form.getlist("item_und")
            descs = request.form.getlist("item_desc")
            parsed = []
            for i, raw_pid in enumerate(pids):
                try:
                    pid = int(raw_pid or 0) or None
                except ValueError:
                    pid = None
                if not pid and not (descs[i] if i < len(descs) else ""):
                    continue
                parsed.append(
                    {
                        "producto_id": pid,
                        "cantidad": cants[i] if i < len(cants) else 0,
                        "precio_unitario": pus[i] if i < len(pus) else 0,
                        "tipo": tipos[i] if i < len(tipos) else "insumo",
                        "unidad": unds[i] if i < len(unds) else "un",
                        "descripcion": descs[i] if i < len(descs) else "",
                    }
                )
            ok, msg, new_id = cst.guardar_apu(
                db,
                apu_id=apu_id,
                obra_id=obra_id,
                codigo=request.form.get("codigo") or "",
                nombre=request.form.get("nombre") or (partida["detalle"] if partida else ""),
                unidad=request.form.get("unidad") or "un",
                leyes_pct=request.form.get("leyes_pct") or 0,
                perdidas_pct=request.form.get("perdidas_pct") or 0,
                notas=request.form.get("notas") or "",
                activo=1 if request.form.get("activo") == "1" else 0,
                items=parsed,
                partida_id=partida_id,
            )
            if ok:
                db.commit()
                flash(msg, "ok")
                db.close()
                return redirect(
                    url_for("constructora_apu_form", obra_id=obra_id, apu_id=new_id)
                )
            db.rollback()
            flash(msg, "danger")
            edit = {
                "id": apu_id,
                "codigo": request.form.get("codigo"),
                "nombre": request.form.get("nombre"),
                "unidad": request.form.get("unidad") or "un",
                "leyes_pct": request.form.get("leyes_pct") or 0,
                "perdidas_pct": request.form.get("perdidas_pct") or 0,
                "notas": request.form.get("notas"),
                "activo": 1 if request.form.get("activo") == "1" else 0,
                "pu_neto": 0,
                "centro_costo_id": obra_id,
            }
            items = parsed

        codigo_def = (edit["codigo"] if edit else None) or cst.next_apu_codigo(
            db, obra_id
        )
        items_view: list[dict] = []
        items_norm = []
        for it in items:
            if isinstance(it, dict):
                pid = it.get("producto_id")
                cant = float(it.get("cantidad") or 0)
                pu = float(it.get("precio_unitario") or 0)
                tipo = (it.get("tipo") or "insumo")
                und = (it.get("unidad") or "un")
                desc = (it.get("descripcion") or "")
            else:
                pid = it["producto_id"] if "producto_id" in it.keys() else None
                cant = float(it["cantidad"] or 0)
                pu = float(it["precio_unitario"] or 0)
                tipo = (it["tipo"] or "insumo")
                und = (it["unidad"] or "un")
                desc = (it["descripcion"] or "")
            items_view.append(
                {
                    "producto_id": pid,
                    "cantidad": cant,
                    "precio_unitario": pu,
                    "tipo": tipo,
                    "unidad": und,
                    "descripcion": desc,
                }
            )
            items_norm.append(
                {
                    "tipo": tipo,
                    "cantidad": cant,
                    "precio_unitario": pu,
                    "total": cant * pu,
                }
            )
        breakdown = cst.calc_apu_desde_items(
            items_norm,
            leyes_pct=float(edit["leyes_pct"] or 0) if edit else 0,
            perdidas_pct=float(edit["perdidas_pct"] or 0) if edit else 0,
        )
        db.close()
        return render_template(
            "constructora/apu_form.html",
            active="constructora",
            edit=edit,
            items=items_view,
            codigo_def=codigo_def,
            breakdown=breakdown,
            slots=max(12, len(items_view) + 4),
            precios=precios,
            obra=obra,
            obra_id=obra_id,
            partida=partida,
            partida_id=partida_id,
            congelado=congelado,
        )

    @app.route("/obras/<int:obra_id>/api/apu/<int:apu_id>.json")
    @app.route("/api/apu/<int:apu_id>.json")
    @login_required
    def constructora_apu_json(apu_id: int, obra_id: int | None = None):
        from flask import jsonify

        db = core.conn()
        cst.ensure_constructora_schema(db)
        row = cst.get_apu(db, apu_id)
        if row and obra_id is not None and int(row["centro_costo_id"] or 0) != int(
            obra_id
        ):
            db.close()
            return jsonify({"ok": False}), 404
        db.close()
        if not row:
            return jsonify({"ok": False}), 404
        return jsonify(
            {
                "ok": True,
                "id": row["id"],
                "codigo": row["codigo"],
                "nombre": row["nombre"],
                "unidad": row["unidad"],
                "pu_neto": float(row["pu_neto"] or 0),
                "obra_id": row["centro_costo_id"],
            }
        )


    # ── Cotización de obra ────────────────────────────────────────
    @app.route("/cotizaciones-obra/nueva", methods=["GET", "POST"])
    @app.route("/cotizaciones-obra/<int:cot_id>/editar", methods=["GET", "POST"])
    @login_required
    def constructora_cotizacion_form(cot_id: int | None = None):
        # LEGACY_COT_OBRA_REDIRECT: el ppto vive en Obras
        flash('El presupuesto ítemizado se arma dentro de cada Obra (pestaña Presupuesto).', 'ok')
        return redirect(url_for('constructora_obras'))

        db = core.conn()
        cst.ensure_constructora_schema(db)
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        obras = cst.list_obras(db, solo_activas=True)
        # APU solo de la obra seleccionada (o prefill)
        _obra_for_apu = None
        try:
            _obra_for_apu = int(request.args.get("obra") or request.form.get("centro_costo_id") or 0) or None
        except ValueError:
            _obra_for_apu = None
        if cot_id:
            _ex = db.execute(
                "SELECT centro_costo_id FROM cotizaciones WHERE id=?", (cot_id,)
            ).fetchone()
            if _ex and _ex["centro_costo_id"]:
                _obra_for_apu = int(_ex["centro_costo_id"])
        apus = cst.list_apu(db, obra_id=_obra_for_apu, solo_activos=True) if _obra_for_apu else []
        edit = None
        items = []
        if cot_id:
            edit = db.execute(
                "SELECT * FROM cotizaciones WHERE id=?", (cot_id,)
            ).fetchone()
            if not edit or (edit["tipo_cotizacion"] or "normal") != "obra":
                flash("Cotización de obra no encontrada.", "danger")
                db.close()
                return redirect(url_for("cotizaciones_list"))
            items = db.execute(
                """
                SELECT * FROM cotizacion_items WHERE cotizacion_id=?
                ORDER BY COALESCE(orden,0), id
                """,
                (cot_id,),
            ).fetchall()
            items = [
                it
                for it in items
                if not core._is_gg_line(it["descripcion"])
                and not core._is_util_line(it["descripcion"])
            ]

        iva_def = core.param(db, "iva", 19)
        gg_def = core.param(db, "gg_pct", 5)
        util_def = core.param(db, "utilidad_pct", 15)
        validez_def = int(core.param(db, "validez_cotizacion", 30))
        apu_map = {int(a["id"]): a for a in apus}

        try:
            obra_prefill = int(request.args.get("obra") or 0) or None
        except ValueError:
            obra_prefill = None

        if request.method == "POST":
            try:
                cliente_id = int(request.form["cliente_id"])
                obra_id = int(request.form.get("centro_costo_id") or 0)
            except (KeyError, ValueError):
                flash("Cliente y obra son obligatorios.", "danger")
                db.close()
                return redirect(request.url)
            if not obra_id:
                flash("Seleccione la obra (CC).", "danger")
                db.close()
                return redirect(request.url)
            obra = db.execute(
                "SELECT * FROM centros_costo WHERE id=? AND COALESCE(tipo,'general')='obra'",
                (obra_id,),
            ).fetchone()
            if not obra:
                flash("Obra inválida.", "danger")
                db.close()
                return redirect(request.url)

            version = (request.form.get("version") or "1").strip().lstrip("Vv") or "1"
            titulo = (request.form.get("titulo") or "").strip() or None
            proyecto = (request.form.get("proyecto") or obra["nombre"] or "").strip()
            asunto = (request.form.get("asunto") or "").strip() or None
            estado = request.form.get("estado") or "borrador"
            fecha = (request.form.get("fecha") or "").strip() or core.hoy_chile().isoformat()
            validez = int(request.form.get("validez") or validez_def)
            gg_pct = float(request.form.get("gg_pct") or gg_def)
            utilidad_pct = float(request.form.get("utilidad_pct") or util_def)
            try:
                iva_pct = float(request.form.get("iva_pct") or iva_def) / 100.0
            except (TypeError, ValueError):
                iva_pct = float(iva_def) / 100.0
            notas = (request.form.get("notas") or "").strip() or None

            descs = request.form.getlist("desc")
            unds = request.form.getlist("und")
            cants = request.form.getlist("cant")
            apu_ids = request.form.getlist("apu_id")
            lineas = []
            orden = 0
            for i, desc in enumerate(descs):
                d = str(desc).strip()
                if not d:
                    continue
                try:
                    aid = int(apu_ids[i] or 0) or None
                except (ValueError, IndexError):
                    aid = None
                cant = float(cants[i] or 0) if i < len(cants) else 0
                if cant <= 0:
                    continue
                if not aid or aid not in apu_map:
                    flash(f"Partida «{d}» requiere un APU.", "danger")
                    db.close()
                    return redirect(request.url)
                pu = float(apu_map[aid]["pu_neto"] or 0)
                und = (unds[i] if i < len(unds) else apu_map[aid]["unidad"] or "un").strip() or "un"
                total = cant * pu
                orden += 1
                lineas.append(
                    {
                        "apu_id": aid,
                        "descripcion": d,
                        "orden": orden,
                        "unidad": und,
                        "cantidad": cant,
                        "precio_unitario": pu,
                        "total": total,
                    }
                )

            if not lineas:
                flash("Agregue al menos una partida con APU y cantidad > 0.", "danger")
            else:
                tots = core.calc_cotizacion_totales(
                    sum(x["total"] for x in lineas), gg_pct, utilidad_pct, iva_pct
                )
                if edit:
                    db.execute(
                        """
                        UPDATE cotizaciones SET
                          cliente_id=?, asunto=?, proyecto=?, estado=?, fecha=?, validez_dias=?,
                          version=?, titulo=?, gg_pct=?, utilidad_pct=?,
                          gg_monto=?, utilidad_monto=?, valor_neto=?,
                          subtotal=?, iva=?, total=?, notas=?, tipo_venta='servicio',
                          tipo_cotizacion='obra', centro_costo_id=?
                        WHERE id=?
                        """,
                        (
                            cliente_id,
                            asunto,
                            proyecto,
                            estado,
                            fecha,
                            validez,
                            version,
                            titulo,
                            gg_pct,
                            utilidad_pct,
                            tots["gg_monto"],
                            tots["utilidad_monto"],
                            tots["valor_neto"],
                            tots["subtotal"],
                            tots["iva"],
                            tots["total"],
                            notas,
                            obra_id,
                            edit["id"],
                        ),
                    )
                    db.execute(
                        "DELETE FROM cotizacion_items WHERE cotizacion_id=?",
                        (edit["id"],),
                    )
                    cid = edit["id"]
                    folio = edit["folio"]
                else:
                    folio = core.next_code(db, "cotizaciones", "folio", "COT")
                    cur = db.cursor()
                    cur.execute(
                        """
                        INSERT INTO cotizaciones
                        (folio, cliente_id, asunto, proyecto, estado, fecha, validez_dias,
                         version, titulo, gg_pct, utilidad_pct,
                         gg_monto, utilidad_monto, valor_neto, subtotal, iva, total, notas,
                         tipo_venta, tipo_cotizacion, centro_costo_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'servicio','obra',?)
                        """,
                        (
                            folio,
                            cliente_id,
                            asunto,
                            proyecto,
                            estado,
                            fecha,
                            validez,
                            version,
                            titulo,
                            gg_pct,
                            utilidad_pct,
                            tots["gg_monto"],
                            tots["utilidad_monto"],
                            tots["valor_neto"],
                            tots["subtotal"],
                            tots["iva"],
                            tots["total"],
                            notas,
                            obra_id,
                        ),
                    )
                    cid = cur.lastrowid

                db.executemany(
                    """
                    INSERT INTO cotizacion_items
                    (cotizacion_id, producto_id, descripcion, obs, orden, unidad,
                     cantidad, precio_unitario, total, apu_id, es_servicio)
                    VALUES (?,NULL,?,?,?,?,?,?,?,?,1)
                    """,
                    [
                        (
                            cid,
                            ln["descripcion"],
                            None,
                            ln["orden"],
                            ln["unidad"],
                            ln["cantidad"],
                            ln["precio_unitario"],
                            ln["total"],
                            ln["apu_id"],
                        )
                        for ln in lineas
                    ],
                )
                if estado == "aprobada":
                    from rmweb import ops as _ops

                    _ops.ensure_ops_schema(db)
                    core.ensure_cxc_from_cotizacion(db, cid)
                    ok_p, msg_p = cst.sincronizar_ppto_obra_desde_cotizacion(db, cid)
                    if ok_p:
                        flash(msg_p, "ok")
                db.commit()
                flash(f"Cotización de obra {folio} guardada.", "ok")
                db.close()
                return redirect(url_for("cotizaciones_detalle", cot_id=cid))

        db.close()
        return render_template(
            "constructora/cotizacion_form.html",
            active="constructora",
            edit=edit,
            items=items,
            clientes=clientes,
            obras=obras,
            apus=apus,
            hoy=core.hoy_chile().isoformat(),
            iva_def=iva_def,
            gg_def=gg_def,
            util_def=util_def,
            validez_def=validez_def,
            estados_cot=list(getattr(core, "ESTADOS_COT", ()) or ())
            or [
                ("borrador", "Borrador"),
                ("enviada", "Enviada"),
                ("aprobada", "Aprobada"),
                ("rechazada", "Rechazada"),
            ],
            titulo_default=(
                edit["titulo"]
                if edit and edit["titulo"]
                else (clientes[0]["razon_social"].upper() if clientes else "")
            ),
            slots=max(10, len(items) + 3),
            obra_prefill=obra_prefill
            or (edit["centro_costo_id"] if edit else None),
        )
