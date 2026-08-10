"""Rutas Flask del módulo Constructora."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for

from rmweb import constructora as cst
from rmweb import core


def register_constructora_routes(app, login_required):
    @app.route("/hub/")
    @login_required
    def constructora_home():
        return redirect(url_for("constructora_obras"))
        db = core.conn()
        cst.ensure_constructora_schema(db)
        obras = cst.list_obras(db)
        apus = cst.list_apu(db, solo_activos=True)
        precios = cst.list_precios_obra(db, solo_activos=True)
        cots = db.execute(
            """
            SELECT c.id, c.folio, c.estado, c.total, c.proyecto, c.subtotal,
                   cc.nombre AS obra_nombre
            FROM cotizaciones c
            LEFT JOIN centros_costo cc ON cc.id=c.centro_costo_id
            WHERE COALESCE(c.tipo_cotizacion,'normal')='obra'
            ORDER BY c.id DESC LIMIT 12
            """
        ).fetchall()
        db.close()
        return render_template(
            "constructora/home.html",
            active="constructora",
            obras=obras,
            apus=apus,
            precios=precios,
            cots=cots,
        )


    # Alias cortos / legado (nginx quita el prefijo /constructora)
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
        obras = cst.list_obras(db)
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        db.close()
        return render_template(
            "constructora/obras.html",
            active="constructora",
            obras=obras,
            clientes=clientes,
            hoy=core.hoy_chile().isoformat(),
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
            presupuesto=request.form.get("presupuesto") or 0,
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
        return redirect(url_for("constructora_obras"))

    @app.route("/obras/<int:obra_id>", methods=["GET", "POST"])
    @login_required
    def constructora_obra_detalle(obra_id: int):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        if request.method == "POST":
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
                presupuesto=request.form.get("presupuesto"),
            )
            if ok:
                db.commit()
                flash(msg, "ok")
            else:
                db.rollback()
                flash(msg, "danger")
            db.close()
            return redirect(url_for("constructora_obra_detalle", obra_id=obra_id))

        resumen = cst.obra_resumen(db, obra_id)
        if not resumen:
            flash("Obra no encontrada.", "danger")
            db.close()
            return redirect(url_for("constructora_obras"))
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        cots = db.execute(
            """
            SELECT id, folio, estado, total, subtotal, fecha
            FROM cotizaciones
            WHERE centro_costo_id=? AND COALESCE(tipo_cotizacion,'normal')='obra'
            ORDER BY id DESC
            """,
            (obra_id,),
        ).fetchall()
        db.close()
        return render_template(
            "constructora/obra_detalle.html",
            active="constructora",
            resumen=resumen,
            obra=resumen["obra"],
            clientes=clientes,
            cots=cots,
        )

    # ── Maestra de precios (productos/insumos de obra) ────────────
    @app.route("/precios/")
    @login_required
    def constructora_precios():
        db = core.conn()
        cst.ensure_constructora_schema(db)
        rows = cst.list_precios_obra(db, solo_activos=False)
        db.close()
        return render_template(
            "constructora/precios.html",
            active="constructora",
            rows=rows,
        )

    @app.route("/precios/nuevo", methods=["GET", "POST"])
    @app.route("/precios/<int:pid>", methods=["GET", "POST"])
    @login_required
    def constructora_precio_form(pid: int | None = None):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        edit = cst.get_precio(db, pid) if pid else None
        if pid and not edit:
            flash("Producto no encontrado.", "danger")
            db.close()
            return redirect(url_for("constructora_precios"))

        if request.method == "POST":
            ok, msg, new_id = cst.guardar_precio(
                db,
                producto_id=pid,
                codigo=request.form.get("codigo") or "",
                nombre=request.form.get("nombre") or "",
                unidad=request.form.get("unidad") or "un",
                precio=request.form.get("precio") or 0,
                tipo_recurso=request.form.get("tipo_recurso") or "insumo",
                activo=1 if request.form.get("activo") == "1" else 0,
                maneja_stock=1 if request.form.get("maneja_stock") == "1" else 0,
            )
            if ok:
                db.commit()
                flash(msg, "ok")
                db.close()
                return redirect(url_for("constructora_precios"))
            db.rollback()
            flash(msg, "danger")
            edit = {
                "id": pid,
                "codigo": request.form.get("codigo"),
                "nombre": request.form.get("nombre"),
                "unidad": request.form.get("unidad") or "un",
                "precio": request.form.get("precio") or 0,
                "tipo_recurso": request.form.get("tipo_recurso") or "insumo",
                "activo": 1 if request.form.get("activo") == "1" else 0,
            }

        tipo_def = (edit["tipo_recurso"] if edit else "insumo") or "insumo"
        codigo_def = (edit["codigo"] if edit and edit["codigo"] else None) or cst.next_precio_codigo(
            db, tipo_def
        )
        db.close()
        return render_template(
            "constructora/precio_form.html",
            active="constructora",
            edit=edit,
            codigo_def=codigo_def,
        )

    # ── Maestra APU ───────────────────────────────────────────────
    @app.route("/apu/")
    @login_required
    def constructora_apu_list():
        db = core.conn()
        cst.ensure_constructora_schema(db)
        rows = cst.list_apu(db)
        db.close()
        return render_template(
            "constructora/apu_lista.html",
            active="constructora",
            rows=rows,
        )

    @app.route("/apu/nuevo", methods=["GET", "POST"])
    @app.route("/apu/<int:apu_id>", methods=["GET", "POST"])
    @login_required
    def constructora_apu_form(apu_id: int | None = None):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        edit = cst.get_apu(db, apu_id) if apu_id else None
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
            return redirect(url_for("constructora_apu_form", apu_id=apu_id))

        if request.method == "POST":
            pids = request.form.getlist("item_producto_id")
            cants = request.form.getlist("item_cant")
            parsed = []
            for i, raw_pid in enumerate(pids):
                try:
                    pid = int(raw_pid or 0) or None
                except ValueError:
                    pid = None
                if not pid:
                    continue
                parsed.append(
                    {
                        "producto_id": pid,
                        "cantidad": cants[i] if i < len(cants) else 0,
                    }
                )
            ok, msg, new_id = cst.guardar_apu(
                db,
                apu_id=apu_id,
                codigo=request.form.get("codigo") or "",
                nombre=request.form.get("nombre") or "",
                unidad=request.form.get("unidad") or "un",
                leyes_pct=request.form.get("leyes_pct") or 0,
                perdidas_pct=request.form.get("perdidas_pct") or 0,
                notas=request.form.get("notas") or "",
                activo=1 if request.form.get("activo") == "1" else 0,
                items=parsed,
            )
            if ok:
                db.commit()
                flash(msg, "ok")
                db.close()
                return redirect(url_for("constructora_apu_form", apu_id=new_id))
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
            }
            items = parsed

        codigo_def = (edit["codigo"] if edit else None) or cst.next_apu_codigo(db)
        items_view: list[dict] = []
        items_norm = []
        for it in items:
            if isinstance(it, dict):
                pid = it.get("producto_id")
                cant = float(it.get("cantidad") or 0)
            else:
                pid = it["producto_id"] if "producto_id" in it.keys() else None
                cant = float(it["cantidad"] or 0)
            master = cst.precio_desde_maestra(db, pid) if pid else None
            pu = float(
                master["precio_unitario"]
                if master
                else (
                    it.get("precio_unitario")
                    if isinstance(it, dict)
                    else (it["precio_unitario"] or 0)
                )
                or 0
            )
            tipo = (
                master["tipo"]
                if master
                else (
                    (it.get("tipo") if isinstance(it, dict) else it["tipo"]) or "insumo"
                )
            )
            items_view.append({"producto_id": pid, "cantidad": cant})
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
            precios=precios,
            codigo_def=codigo_def,
            breakdown=breakdown,
            slots=max(12, len(items_view) + 4),
        )

    @app.route("/api/apu/<int:apu_id>.json")
    @login_required
    def constructora_apu_json(apu_id: int):
        from flask import jsonify

        db = core.conn()
        cst.ensure_constructora_schema(db)
        row = cst.get_apu(db, apu_id)
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
            }
        )

    # ── Cotización de obra ────────────────────────────────────────
    @app.route("/cotizaciones-obra/nueva", methods=["GET", "POST"])
    @app.route("/cotizaciones-obra/<int:cot_id>/editar", methods=["GET", "POST"])
    @login_required
    def constructora_cotizacion_form(cot_id: int | None = None):
        db = core.conn()
        cst.ensure_constructora_schema(db)
        clientes = db.execute(
            "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        obras = cst.list_obras(db, solo_activas=True)
        apus = cst.list_apu(db, solo_activos=True)
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
