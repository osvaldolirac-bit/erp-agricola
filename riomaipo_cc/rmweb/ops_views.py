"""Rutas Flask para Compras, Tesorería (CxP), Bodega y Ventas."""
from __future__ import annotations

from datetime import date, timedelta
from functools import wraps

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from rmweb import core
from rmweb import ops
from rmweb import ops_cc


def register_ops_routes(app, login_required):
    """Registra módulos operativos. login_required = decorator del app."""

    @app.context_processor
    def _ops_inject():
        return {
            "cxp_estado_class": ops.cxp_estado_class,
            "cxp_estado_label": ops.cxp_estado_label,
        }

    # ── Centros de costo (reporte) ────────────────────────────────
    @app.route("/centros-costo/")
    @login_required
    def centros_costo():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        desde = (request.args.get("desde") or "").strip()
        hasta = (request.args.get("hasta") or "").strip()
        tab = (request.args.get("tab") or "resumen").strip()
        centros = ops_cc.list_centros(db, solo_activos=True)
        matriz = ops_cc.matriz_cc_rubros(db, desde=desde or None, hasta=hasta or None)
        detalle_cc = None
        cc_activo = None
        if tab.startswith("cc-"):
            try:
                cc_id = int(tab.split("-", 1)[1])
            except (IndexError, ValueError):
                cc_id = 0
            for cc in centros:
                if int(cc["id"]) == cc_id:
                    cc_activo = cc
                    break
            if cc_activo is None:
                tab = "resumen"
            else:
                detalle_cc = ops_cc.detalle_por_centro(
                    db, cc_id, desde=desde or None, hasta=hasta or None
                )
        else:
            tab = "resumen"
        db.close()
        return render_template(
            "centros_costo.html",
            active="centros",
            tab=tab,
            centros=centros,
            matriz=matriz,
            detalle_cc=detalle_cc,
            cc_activo=cc_activo,
            desde=desde,
            hasta=hasta,
        )

    # ── Admin: catálogo centros de costo ──────────────────────────
    @app.route("/admin/centros", methods=["POST"])
    @login_required
    def admin_centros():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        action = (request.form.get("action") or "").strip()
        if action == "crear":
            ok, msg = ops_cc.crear_centro(
                db,
                request.form.get("nombre") or "",
                presupuesto=request.form.get("presupuesto"),
            )
            if ok:
                db.commit()
                flash(msg, "ok")
            else:
                db.rollback()
                flash(msg, "danger")
        elif action == "actualizar":
            try:
                cc_id = int(request.form.get("cc_id") or 0)
            except ValueError:
                cc_id = 0
            activo = 1 if request.form.get("activo") == "1" else 0
            ok, msg = ops_cc.actualizar_centro(
                db,
                cc_id,
                nombre=request.form.get("nombre"),
                activo=activo,
                presupuesto=request.form.get("presupuesto"),
            )
            if ok:
                db.commit()
                flash(msg, "ok")
            else:
                db.rollback()
                flash(msg, "danger")
        else:
            flash("Acción no reconocida.", "danger")
        db.close()
        return redirect(url_for("admin", tab="centros"))

    @app.route("/admin/rubros", methods=["POST"])
    @login_required
    def admin_rubros():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        action = (request.form.get("action") or "").strip()
        if action == "crear":
            ok, msg = ops_cc.crear_rubro(db, request.form.get("nombre") or "")
        elif action == "actualizar":
            try:
                rubro_id = int(request.form.get("rubro_id") or 0)
            except ValueError:
                rubro_id = 0
            activo = 1 if request.form.get("activo") == "1" else 0
            ok, msg = ops_cc.actualizar_rubro(
                db,
                rubro_id,
                nombre=request.form.get("nombre"),
                activo=activo,
            )
        elif action == "eliminar":
            try:
                rubro_id = int(request.form.get("rubro_id") or 0)
            except ValueError:
                rubro_id = 0
            ok, msg = ops_cc.eliminar_rubro(db, rubro_id)
        else:
            ok, msg = False, "Acción no reconocida."
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            db.rollback()
            flash(msg, "danger")
        db.close()
        return redirect(url_for("admin", tab="centros"))

    # ── Proveedores ───────────────────────────────────────────────
    @app.route("/proveedores/")
    @login_required
    def proveedores_list():
        q = (request.args.get("q") or "").strip()
        db = core.conn()
        ops.ensure_ops_schema(db)
        sql = "SELECT * FROM proveedores WHERE 1=1"
        params: list = []
        if q:
            like = f"%{q}%"
            sql += " AND (rut LIKE ? OR razon_social LIKE ? OR email LIKE ? OR contacto LIKE ?)"
            params.extend([like, like, like, like])
        sql += " ORDER BY razon_social"
        rows = db.execute(sql, params).fetchall()
        db.close()
        return render_template(
            "proveedores/lista.html", active="compras", rows=rows, q=q
        )

    @app.route("/proveedores/nuevo", methods=["GET", "POST"])
    @app.route("/proveedores/<int:pid>/editar", methods=["GET", "POST"])
    @login_required
    def proveedores_form(pid: int | None = None):
        db = core.conn()
        ops.ensure_ops_schema(db)
        row = (
            db.execute("SELECT * FROM proveedores WHERE id=?", (pid,)).fetchone()
            if pid
            else None
        )
        if request.method == "POST":
            data = (
                request.form.get("rut", "").strip() or None,
                request.form.get("razon_social", "").strip(),
                request.form.get("contacto", "").strip() or None,
                request.form.get("telefono", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form.get("direccion", "").strip() or None,
                1 if request.form.get("activo") else 0,
            )
            if not data[1]:
                flash("La razón social es obligatoria", "danger")
            else:
                try:
                    if row:
                        db.execute(
                            """
                            UPDATE proveedores SET rut=?, razon_social=?, contacto=?, telefono=?,
                            email=?, direccion=?, activo=? WHERE id=?
                            """,
                            (*data, row["id"]),
                        )
                    else:
                        db.execute(
                            """
                            INSERT INTO proveedores
                            (rut, razon_social, contacto, telefono, email, direccion, activo, creado_en)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (*data, core.hoy_chile().isoformat()),
                        )
                    db.commit()
                    flash("Proveedor guardado", "ok")
                    db.close()
                    return redirect(url_for("proveedores_list"))
                except Exception as exc:
                    flash(f"No se pudo guardar: {exc}", "danger")
        db.close()
        return render_template(
            "proveedores/form.html", active="compras", row=row
        )

    # ── Compras ───────────────────────────────────────────────────
    @app.route("/compras/")
    @login_required
    def compras_list():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        rows = db.execute(
            """
            SELECT f.*, p.razon_social AS proveedor, o.folio AS oc_folio,
                   rg.nombre AS rubro_nombre,
                   (
                     SELECT GROUP_CONCAT(cc.nombre, ', ')
                     FROM factura_compra_cc fcc
                     JOIN centros_costo cc ON cc.id = fcc.centro_costo_id
                     WHERE fcc.factura_id = f.id
                   ) AS centros_txt
            FROM facturas_compra f
            LEFT JOIN proveedores p ON p.id = f.proveedor_id
            LEFT JOIN ordenes_compra o ON o.id = f.orden_compra_id
            LEFT JOIN rubros_gasto rg ON rg.id = f.rubro_id
            ORDER BY COALESCE(f.fecha_emision,'') DESC, f.id DESC
            """
        ).fetchall()
        kpis = ops.kpis_cxp(db)
        db.close()
        return render_template(
            "compras/lista.html", active="compras", rows=rows, kpis=kpis
        )


    @app.route("/compras/nueva", methods=["GET", "POST"])
    @app.route("/compras/<int:fid>/editar", methods=["GET", "POST"])
    @login_required
    def compras_form(fid: int | None = None):
        from rmweb import ops_oc

        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        ops_cc.ensure_cc_schema(db)
        row = (
            db.execute("SELECT * FROM facturas_compra WHERE id=?", (fid,)).fetchone()
            if fid
            else None
        )
        items = []
        oc = None
        ocs_disp = []
        sugerido_documento = ""
        cc_selected: list[int] = []

        if row:
            items = db.execute(
                "SELECT * FROM factura_compra_items WHERE factura_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
            cc_selected = [
                int(r["centro_costo_id"])
                for r in ops_cc.imputaciones_factura(db, int(row["id"]))
            ]
            if row["orden_compra_id"]:
                oc = ops_oc.cargar_oc(db, int(row["orden_compra_id"]))
        else:
            # Nueva compra: exige OC (?oc= o selector)
            try:
                oc_id = int(request.args.get("oc") or request.form.get("orden_compra_id") or 0)
            except ValueError:
                oc_id = 0
            if oc_id:
                oc = ops_oc.cargar_oc(db, oc_id)
                if not ops_oc.oc_disponible(oc):
                    db.close()
                    flash("La OC no está disponible para emitir compra", "danger")
                    return redirect(url_for("compras_form"))
                items = db.execute(
                    "SELECT * FROM orden_compra_items WHERE orden_id=? ORDER BY id",
                    (oc_id,),
                ).fetchall()
                sugerido_documento = ""  # usuario anota factura real del proveedor
            else:
                ocs_disp = ops_oc.ocs_disponibles(db)

        proveedores = db.execute(
            "SELECT id, razon_social FROM proveedores WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        productos = db.execute(
            "SELECT id, codigo, nombre, unidad, precio, COALESCE(es_servicio,0) AS es_servicio FROM productos WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        rubros = ops_cc.list_rubros(db, solo_activos=True)
        centros = ops_cc.list_centros(db, solo_activos=True)

        def _render_form(**extra):
            ctx = dict(
                active="compras",
                row=row,
                items=items,
                proveedores=proveedores,
                productos=productos,
                rubros=rubros,
                centros=centros,
                cc_selected=cc_selected,
                oc=oc,
                ocs_disponibles=ocs_disp,
                sugerido_documento=sugerido_documento,
                hoy=core.hoy_chile().isoformat(),
            )
            ctx.update(extra)
            return render_template("compras/form.html", **ctx)

        if request.method == "POST" and (row or oc):
            try:
                proveedor_id = int(request.form.get("proveedor_id") or 0)
            except ValueError:
                proveedor_id = 0
            documento = (request.form.get("documento") or "").strip()
            tipo_documento = (request.form.get("tipo_documento") or "factura").strip().lower() or "factura"
            concepto = (request.form.get("concepto") or "").strip()
            fe = (request.form.get("fecha_emision") or core.hoy_chile().isoformat()).strip()
            try:
                dias = int(request.form.get("dias_credito") or 30)
            except ValueError:
                dias = 30
            fv = (request.form.get("fecha_vencimiento") or "").strip()
            if not fv:
                fv = (date.fromisoformat(fe) + timedelta(days=max(0, dias))).isoformat()
            afecta_stock = 1 if request.form.get("afecta_stock") else 0
            notas = (request.form.get("notas") or "").strip()
            try:
                rubro_id = int(request.form.get("rubro_id") or 0)
            except ValueError:
                rubro_id = 0
            cc_base = ops_cc.normalizar_cc_base(
                "bruto" if request.form.get("imputar_bruto") else "neto"
            )
            cc_raw = (request.form.get("centro_costo_id") or "").strip()
            try:
                cc_selected = [int(cc_raw)] if cc_raw else []
            except ValueError:
                cc_selected = []
            if len(cc_selected) > 1:
                cc_selected = cc_selected[:1]

            try:
                orden_compra_id = int(request.form.get("orden_compra_id") or 0) or None
            except ValueError:
                orden_compra_id = None
            if row and row["orden_compra_id"]:
                orden_compra_id = int(row["orden_compra_id"])

            descs = request.form.getlist("item_desc")
            uns = request.form.getlist("item_unidad")
            cants = request.form.getlist("item_cant")
            costos = request.form.getlist("item_costo")
            pids = request.form.getlist("item_producto_id")

            lineas = []
            neto = 0.0
            for i, desc in enumerate(descs):
                desc = (desc or "").strip()
                if not desc:
                    continue
                try:
                    cant = float(cants[i] or 1)
                except (IndexError, ValueError):
                    cant = 1.0
                try:
                    costo = float(costos[i] or 0)
                except (IndexError, ValueError):
                    costo = 0.0
                try:
                    pid = int(pids[i] or 0) or None
                except (IndexError, ValueError):
                    pid = None
                try:
                    un = (uns[i] or "un").strip() or "un"
                except IndexError:
                    un = "un"
                es_serv = 1 if request.form.get(f"item_servicio_{i}") else 0
                if not es_serv and pid:
                    prow = next((p for p in productos if int(p["id"]) == pid), None)
                    if prow and int(prow["es_servicio"] or 0):
                        es_serv = 1
                total_l = cant * costo
                neto += total_l
                lineas.append((pid, desc, un, cant, costo, total_l, es_serv))

            if not row and not orden_compra_id:
                flash("Debe vincular la compra a una Orden de compra", "danger")
            elif not row and orden_compra_id:
                oc_chk = ops_oc.cargar_oc(db, int(orden_compra_id))
                if not ops_oc.oc_disponible(oc_chk):
                    flash("La OC ya no está disponible", "danger")
                    db.close()
                    return redirect(url_for("compras_form"))
                proveedor_id = int(oc_chk["proveedor_id"])
                if not concepto:
                    concepto = oc_chk["concepto"] or f"Según {oc_chk['folio']}"
                if notas and oc_chk["folio"] not in notas:
                    notas = f"{notas} · Origen {oc_chk['folio']}"
                elif not notas:
                    notas = f"Origen {oc_chk['folio']}"

            if not proveedor_id or not documento:
                flash("Proveedor y Nº factura del proveedor son obligatorios", "danger")
            elif not lineas:
                flash("Agregue al menos un ítem", "danger")
            elif not rubro_id:
                flash("Seleccione el rubro de gasto", "danger")
            elif not cc_selected:
                flash("Seleccione un centro de costo", "danger")
            elif not row and not orden_compra_id:
                pass  # ya flasheado
            else:
                iva_pct = 19.0
                try:
                    iva_pct = float(
                        (
                            db.execute(
                                "SELECT valor FROM parametros WHERE clave='iva'"
                            ).fetchone()
                            or {"valor": "19"}
                        )["valor"]
                        or 19
                    )
                except Exception:
                    iva_pct = 19.0
                iva = neto * iva_pct / 100.0
                total = neto + iva
                monto_cc = ops_cc.monto_base_imputacion(neto, total, cc_base)
                try:
                    if row:
                        db.execute(
                            """
                            UPDATE facturas_compra SET documento=?, tipo_documento=?, proveedor_id=?, concepto=?,
                            fecha_emision=?, fecha_vencimiento=?, neto=?, iva=?, total=?,
                            afecta_stock=?, notas=?, rubro_id=?, cc_base=? WHERE id=?
                            """,
                            (
                                documento,
                                tipo_documento,
                                proveedor_id,
                                concepto,
                                fe,
                                fv,
                                neto,
                                iva,
                                total,
                                afecta_stock,
                                notas,
                                rubro_id,
                                cc_base,
                                row["id"],
                            ),
                        )
                        db.execute(
                            "DELETE FROM factura_compra_items WHERE factura_id=?",
                            (row["id"],),
                        )
                        fid_use = int(row["id"])
                    else:
                        cur = db.execute(
                            """
                            INSERT INTO facturas_compra
                            (documento, tipo_documento, proveedor_id, concepto, fecha_emision, fecha_vencimiento,
                             neto, iva, total, pagado, saldo, estado, afecta_stock, notas, orden_compra_id, rubro_id, cc_base)
                            VALUES (?,?,?,?,?,?,?,?,?,0,?,'pendiente',?,?,?,?,?)
                            """,
                            (
                                documento,
                                tipo_documento,
                                proveedor_id,
                                concepto,
                                fe,
                                fv,
                                neto,
                                iva,
                                total,
                                total,
                                afecta_stock,
                                notas,
                                orden_compra_id,
                                rubro_id,
                                cc_base,
                            ),
                        )
                        fid_use = int(cur.lastrowid)
                        db.execute(
                            "UPDATE ordenes_compra SET estado='convertida', factura_id=? WHERE id=?",
                            (fid_use, orden_compra_id),
                        )
                    for pid, desc, un, cant, costo, total_l, es_serv in lineas:
                        db.execute(
                            """
                            INSERT INTO factura_compra_items
                            (factura_id, producto_id, descripcion, unidad, cantidad, costo_unitario, total, es_servicio)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (fid_use, pid, desc, un, cant, costo, total_l, es_serv),
                        )
                    ok_cc, msg_cc = ops_cc.guardar_imputacion_cc(
                        db, fid_use, cc_selected, monto_cc
                    )
                    if not ok_cc:
                        db.rollback()
                        flash(msg_cc, "danger")
                        db.close()
                        return _render_form()
                    ops.recalc_factura_compra(db, fid_use)
                    if not row and afecta_stock:
                        ok, msg = ops.aplicar_entrada_compra(db, fid_use)
                        if not ok:
                            db.rollback()
                            flash(msg, "danger")
                            db.close()
                            return _render_form()
                    db.commit()
                    flash("Compra guardada" if row else "Compra emitida desde OC", "ok")
                    db.close()
                    return redirect(url_for("compras_detalle", fid=fid_use))
                except Exception as exc:
                    db.rollback()
                    flash(f"No se pudo guardar: {exc}", "danger")

        db.close()
        return _render_form()


    @app.route("/compras/<int:fid>")
    @login_required
    def compras_detalle(fid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        row = db.execute(
            """
            SELECT f.*, p.razon_social AS proveedor, p.rut AS proveedor_rut,
                   rg.nombre AS rubro_nombre
            FROM facturas_compra f
            LEFT JOIN proveedores p ON p.id=f.proveedor_id
            LEFT JOIN rubros_gasto rg ON rg.id=f.rubro_id
            WHERE f.id=?
            """,
            (fid,),
        ).fetchone()
        if not row:
            db.close()
            flash("Documento no encontrado", "danger")
            return redirect(url_for("compras_list"))
        items = db.execute(
            "SELECT * FROM factura_compra_items WHERE factura_id=? ORDER BY id",
            (fid,),
        ).fetchall()
        pagos = db.execute(
            "SELECT * FROM pagos_compra WHERE factura_id=? ORDER BY fecha DESC, id DESC",
            (fid,),
        ).fetchall()
        imputaciones = ops_cc.imputaciones_factura(db, fid)
        db.close()
        return render_template(
            "compras/detalle.html",
            active="compras",
            row=row,
            items=items,
            pagos=pagos,
            imputaciones=imputaciones,
        )

    # ── Tesorería (CxP) ───────────────────────────────────────────
    @app.route("/tesoreria/")
    @login_required
    def tesoreria_list():
        db = core.conn()
        ops.ensure_ops_schema(db)
        rows = db.execute(
            """
            SELECT f.*, p.razon_social AS proveedor
            FROM facturas_compra f
            LEFT JOIN proveedores p ON p.id=f.proveedor_id
            WHERE COALESCE(f.saldo,0) > 0.009
            ORDER BY COALESCE(f.fecha_vencimiento, f.fecha_emision) ASC, f.id
            """
        ).fetchall()
        kpis = ops.kpis_cxp(db)
        recientes = db.execute(
            """
            SELECT pg.*, f.documento, p.razon_social AS proveedor
            FROM pagos_compra pg
            JOIN facturas_compra f ON f.id=pg.factura_id
            LEFT JOIN proveedores p ON p.id=f.proveedor_id
            ORDER BY pg.id DESC LIMIT 15
            """
        ).fetchall()
        db.close()
        return render_template(
            "tesoreria/lista.html",
            active="tesoreria",
            rows=rows,
            kpis=kpis,
            recientes=recientes,
        )

    @app.route("/tesoreria/<int:fid>/pago", methods=["GET", "POST"])
    @login_required
    def tesoreria_pago(fid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        row = db.execute(
            """
            SELECT f.*, p.razon_social AS proveedor
            FROM facturas_compra f
            LEFT JOIN proveedores p ON p.id=f.proveedor_id
            WHERE f.id=?
            """,
            (fid,),
        ).fetchone()
        if not row:
            db.close()
            flash("Documento no encontrado", "danger")
            return redirect(url_for("tesoreria_list"))
        if request.method == "POST":
            try:
                monto = float(request.form.get("monto") or 0)
            except ValueError:
                monto = 0
            medio = (request.form.get("medio") or "transferencia").strip()
            nota = (request.form.get("nota") or "").strip()
            fecha = (request.form.get("fecha") or core.hoy_chile().isoformat()).strip()
            saldo = float(row["saldo"] or 0)
            if monto <= 0:
                flash("Monto inválido", "danger")
            elif monto > saldo + 0.01:
                flash("El monto supera el saldo", "danger")
            else:
                db.execute(
                    """
                    INSERT INTO pagos_compra (factura_id, fecha, monto, medio, nota)
                    VALUES (?,?,?,?,?)
                    """,
                    (fid, fecha, monto, medio, nota),
                )
                ops.recalc_factura_compra(db, fid)
                db.commit()
                flash(f"Pago de {core.clp(monto)} registrado", "ok")
                db.close()
                return redirect(url_for("tesoreria_list"))
        db.close()
        return render_template(
            "tesoreria/pago.html",
            active="tesoreria",
            row=row,
            hoy=core.hoy_chile().isoformat(),
        )

    # ── Bodega ────────────────────────────────────────────────────
    @app.route("/bodega/")
    @login_required
    def bodega_list():
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_cc.ensure_cc_schema(db)
        try:
            from rmweb import constructora as _cst
            _cst.ensure_constructora_schema(db)
        except Exception:
            pass
        rows = db.execute(
            """
            SELECT i.*, p.codigo AS prod_codigo
            FROM inventario i
            LEFT JOIN productos p ON p.id=i.producto_id
            WHERE i.activo=1
            ORDER BY i.nombre
            """
        ).fetchall()
        movs = db.execute(
            """
            SELECT m.*, i.nombre, cc.nombre AS cc_nombre
            FROM inventario_movimientos m
            JOIN inventario i ON i.id=m.inventario_id
            LEFT JOIN centros_costo cc ON cc.id=m.centro_costo_id
            ORDER BY m.id DESC LIMIT 30
            """
        ).fetchall()
        productos = db.execute(
            """
            SELECT id, codigo, nombre, unidad FROM productos
            WHERE activo=1 AND COALESCE(es_servicio,0)=0
            ORDER BY nombre
            """
        ).fetchall()
        catalogo = db.execute(
            """
            SELECT id, codigo, nombre, unidad, precio,
                   COALESCE(es_servicio,0) AS es_servicio,
                   COALESCE(maneja_stock,0) AS maneja_stock,
                   COALESCE(activo,1) AS activo
            FROM productos
            ORDER BY nombre
            """
        ).fetchall()
        centros = ops_cc.list_centros(db, solo_activos=True)
        db.close()
        return render_template(
            "bodega/lista.html",
            active="bodega",
            rows=rows,
            movs=movs,
            productos=productos,
            catalogo=catalogo,
            centros=centros,
            hoy=core.hoy_chile().isoformat(),
        )

    @app.route("/bodega/movimiento", methods=["POST"])
    @login_required
    def bodega_movimiento():
        db = core.conn()
        ops.ensure_ops_schema(db)
        tipo = (request.form.get("tipo") or "entrada").strip()
        try:
            cantidad = float(request.form.get("cantidad") or 0)
        except ValueError:
            cantidad = 0
        try:
            costo = float(request.form.get("costo") or 0)
        except ValueError:
            costo = 0
        try:
            pid = int(request.form.get("producto_id") or 0) or None
        except ValueError:
            pid = None
        try:
            cc_id = int(request.form.get("centro_costo_id") or 0) or None
        except ValueError:
            cc_id = None
        nombre = (request.form.get("nombre") or "").strip()
        unidad = (request.form.get("unidad") or "un").strip() or "un"
        nota = (request.form.get("nota") or "").strip()
        fecha = (request.form.get("fecha") or core.hoy_chile().isoformat()).strip()
        ok, msg = ops.registrar_movimiento_stock(
            db,
            tipo=tipo,
            cantidad=cantidad,
            costo_unitario=costo,
            producto_id=pid,
            nombre=nombre,
            unidad=unidad,
            origen="manual",
            nota=nota,
            fecha=fecha,
            centro_costo_id=cc_id,
        )
        if ok:
            db.commit()
            flash(msg, "ok")
        else:
            flash(msg, "danger")
        db.close()
        return redirect(url_for("bodega_list"))


    @app.route("/bodega/productos/nuevo", methods=["GET", "POST"])
    @app.route("/bodega/productos/<int:pid>/editar", methods=["GET", "POST"])
    @login_required
    def bodega_producto_form(pid: int | None = None):
        db = core.conn()
        ops.ensure_ops_schema(db)
        edit = None
        if pid:
            edit = db.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
            if not edit:
                db.close()
                flash("Producto no encontrado", "danger")
                return redirect(url_for("bodega_list"))
        if request.method == "POST":
            codigo = (request.form.get("codigo") or "").strip() or None
            nombre = (request.form.get("nombre") or "").strip()
            unidad = (request.form.get("unidad") or "un").strip() or "un"
            try:
                precio = float(request.form.get("precio") or 0)
            except ValueError:
                precio = 0.0
            es_servicio = 1 if request.form.get("es_servicio") == "1" else 0
            maneja_stock = 0 if es_servicio else (1 if request.form.get("maneja_stock") == "1" else 0)
            activo = 1 if request.form.get("activo") == "1" else 0
            if not nombre:
                flash("Nombre obligatorio", "danger")
            else:
                try:
                    if edit:
                        db.execute(
                            """
                            UPDATE productos SET codigo=?, nombre=?, unidad=?, precio=?,
                              es_servicio=?, maneja_stock=?, activo=?
                            WHERE id=?
                            """,
                            (codigo, nombre, unidad, precio, es_servicio, maneja_stock, activo, edit["id"]),
                        )
                        flash("Producto actualizado", "ok")
                        pid_out = int(edit["id"])
                    else:
                        cur = db.execute(
                            """
                            INSERT INTO productos (codigo, nombre, unidad, precio, es_servicio, maneja_stock, activo)
                            VALUES (?,?,?,?,?,?,?)
                            """,
                            (codigo, nombre, unidad, precio, es_servicio, maneja_stock, activo),
                        )
                        pid_out = int(cur.lastrowid)
                        flash("Producto creado", "ok")
                    if maneja_stock and not es_servicio:
                        ops._get_or_create_inventario(
                            db,
                            producto_id=pid_out,
                            codigo=codigo or "",
                            nombre=nombre,
                            unidad=unidad,
                        )
                    db.commit()
                    db.close()
                    return redirect(url_for("bodega_list"))
                except Exception as exc:  # noqa: BLE001
                    flash(f"No se pudo guardar: {exc}", "danger")
        db.close()
        return render_template(
            "bodega/producto_form.html",
            active="bodega",
            edit=edit,
        )

    @app.route("/bodega/productos/<int:pid>/toggle", methods=["POST"])
    @login_required
    def bodega_producto_toggle(pid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        row = db.execute("SELECT id, activo FROM productos WHERE id=?", (pid,)).fetchone()
        if not row:
            flash("Producto no encontrado", "danger")
        else:
            nuevo = 0 if int(row["activo"] or 0) else 1
            db.execute("UPDATE productos SET activo=? WHERE id=?", (nuevo, pid))
            db.commit()
            flash("Producto activado" if nuevo else "Producto desactivado", "ok")
        db.close()
        return redirect(url_for("bodega_list"))


    # ── Ventas (remitos) ──────────────────────────────────────────
    @app.route("/ventas/")
    @login_required
    def ventas_list():
        db = core.conn()
        ops.ensure_ops_schema(db)
        remitos = db.execute(
            """
            SELECT r.*, cl.razon_social AS cliente, cot.folio AS cot_folio
            FROM remitos_venta r
            LEFT JOIN clientes cl ON cl.id=r.cliente_id
            LEFT JOIN cotizaciones cot ON cot.id=r.cotizacion_id
            ORDER BY r.id DESC
            """
        ).fetchall()
        # Cotizaciones aprobadas sin remito (candidatas)
        candidatas = db.execute(
            """
            SELECT c.id, c.folio, c.asunto, c.total, c.fecha, c.cxc_id, cl.razon_social AS cliente
            FROM cotizaciones c
            LEFT JOIN clientes cl ON cl.id=c.cliente_id
            WHERE c.estado='aprobada'
              AND NOT EXISTS (SELECT 1 FROM remitos_venta r WHERE r.cotizacion_id=c.id)
            ORDER BY c.fecha DESC, c.id DESC
            """
        ).fetchall()
        db.close()
        return render_template(
            "ventas/lista.html",
            active="ventas",
            remitos=remitos,
            candidatas=candidatas,
        )

    @app.route("/ventas/desde-cotizacion/<int:cot_id>", methods=["GET", "POST"])
    @login_required
    def ventas_desde_cotizacion(cot_id: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        cot = db.execute(
            """
            SELECT c.*, cl.razon_social AS cliente
            FROM cotizaciones c
            LEFT JOIN clientes cl ON cl.id=c.cliente_id
            WHERE c.id=?
            """,
            (cot_id,),
        ).fetchone()
        if not cot or cot["estado"] != "aprobada":
            db.close()
            flash("Solo cotizaciones aprobadas", "danger")
            return redirect(url_for("ventas_list"))
        ya = db.execute(
            "SELECT id FROM remitos_venta WHERE cotizacion_id=?", (cot_id,)
        ).fetchone()
        if ya:
            db.close()
            flash("Esta cotización ya tiene remito", "danger")
            return redirect(url_for("ventas_detalle", rid=ya["id"]))
        items = db.execute(
            """
            SELECT id, producto_id, descripcion, unidad, cantidad, precio_unitario, total
            FROM cotizacion_items WHERE cotizacion_id=? ORDER BY orden, id
            """,
            (cot_id,),
        ).fetchall()
        # hint servicio from producto
        prod_serv = {
            int(r["id"]): int(r["es_servicio"] or 0)
            for r in db.execute(
                "SELECT id, COALESCE(es_servicio,0) AS es_servicio FROM productos"
            ).fetchall()
        }

        if request.method == "POST":
            fecha = (request.form.get("fecha") or core.hoy_chile().isoformat()).strip()
            notas = (request.form.get("notas") or "").strip()
            folio = ops.next_remito_folio(db)
            lineas = []
            for it in items:
                iid = int(it["id"])
                if not request.form.get(f"incluir_{iid}"):
                    continue
                es_serv = 1 if request.form.get(f"servicio_{iid}") else 0
                try:
                    cant = float(request.form.get(f"cant_{iid}") or it["cantidad"] or 1)
                except ValueError:
                    cant = float(it["cantidad"] or 1)
                lineas.append((it, es_serv, cant))
            if not lineas:
                flash("Seleccione al menos un ítem", "danger")
            else:
                try:
                    cur = db.execute(
                        """
                        INSERT INTO remitos_venta
                        (folio, cotizacion_id, cliente_id, fecha, notas, cxc_id)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (
                            folio,
                            cot_id,
                            cot["cliente_id"],
                            fecha,
                            notas,
                            cot["cxc_id"],
                        ),
                    )
                    rid = int(cur.lastrowid)
                    for it, es_serv, cant in lineas:
                        db.execute(
                            """
                            INSERT INTO remito_venta_items
                            (remito_id, descripcion, unidad, cantidad, es_servicio, producto_id, cotizacion_item_id)
                            VALUES (?,?,?,?,?,?,?)
                            """,
                            (
                                rid,
                                it["descripcion"],
                                it["unidad"] or "un",
                                cant,
                                es_serv,
                                it["producto_id"],
                                it["id"],
                            ),
                        )
                        if not es_serv:
                            ok, msg = ops.registrar_movimiento_stock(
                                db,
                                tipo="salida",
                                cantidad=cant,
                                producto_id=it["producto_id"],
                                nombre=it["descripcion"],
                                unidad=it["unidad"] or "un",
                                origen="venta",
                                origen_id=rid,
                                nota=f"Remito {folio}",
                                fecha=fecha,
                            )
                            if not ok:
                                db.rollback()
                                flash(msg, "danger")
                                db.close()
                                return redirect(
                                    url_for("ventas_desde_cotizacion", cot_id=cot_id)
                                )
                    db.commit()
                    flash(
                        f"Remito {folio} creado"
                        + (
                            f" · CxC vinculada"
                            if cot["cxc_id"]
                            else " · sin CxC (revise cobranza)"
                        ),
                        "ok",
                    )
                    db.close()
                    return redirect(url_for("ventas_detalle", rid=rid))
                except Exception as exc:
                    flash(f"No se pudo crear remito: {exc}", "danger")

        db.close()
        return render_template(
            "ventas/desde_cot.html",
            active="ventas",
            cot=cot,
            items=items,
            prod_serv=prod_serv,
            hoy=core.hoy_chile().isoformat(),
        )

    @app.route("/ventas/<int:rid>")
    @login_required
    def ventas_detalle(rid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        row = db.execute(
            """
            SELECT r.*, cl.razon_social AS cliente, cot.folio AS cot_folio, cot.total AS cot_total
            FROM remitos_venta r
            LEFT JOIN clientes cl ON cl.id=r.cliente_id
            LEFT JOIN cotizaciones cot ON cot.id=r.cotizacion_id
            WHERE r.id=?
            """,
            (rid,),
        ).fetchone()
        if not row:
            db.close()
            flash("Remito no encontrado", "danger")
            return redirect(url_for("ventas_list"))
        items = db.execute(
            "SELECT * FROM remito_venta_items WHERE remito_id=? ORDER BY id",
            (rid,),
        ).fetchall()
        db.close()
        return render_template(
            "ventas/detalle.html", active="ventas", row=row, items=items
        )
