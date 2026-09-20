#!/usr/bin/env python3
"""Compra nueva obligatoriamente vinculada a una OC."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
SRC = Path(__file__).resolve().parents[1] / "rmweb"

NEW_COMPRAS_FORM = r'''
    @app.route("/compras/nueva", methods=["GET", "POST"])
    @app.route("/compras/<int:fid>/editar", methods=["GET", "POST"])
    @login_required
    def compras_form(fid: int | None = None):
        from rmweb import ops_oc

        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        row = (
            db.execute("SELECT * FROM facturas_compra WHERE id=?", (fid,)).fetchone()
            if fid
            else None
        )
        items = []
        oc = None
        ocs_disp = []
        sugerido_documento = ""

        if row:
            items = db.execute(
                "SELECT * FROM factura_compra_items WHERE factura_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
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
                sugerido_documento = f"FC-{oc['folio']}"
            else:
                ocs_disp = ops_oc.ocs_disponibles(db)

        proveedores = db.execute(
            "SELECT id, razon_social FROM proveedores WHERE activo=1 ORDER BY razon_social"
        ).fetchall()
        productos = db.execute(
            "SELECT id, codigo, nombre, unidad, precio, COALESCE(es_servicio,0) AS es_servicio FROM productos WHERE activo=1 ORDER BY nombre"
        ).fetchall()

        if request.method == "POST" and (row or oc):
            try:
                proveedor_id = int(request.form.get("proveedor_id") or 0)
            except ValueError:
                proveedor_id = 0
            documento = (request.form.get("documento") or "").strip()
            concepto = (request.form.get("concepto") or "").strip()
            fe = (request.form.get("fecha_emision") or date.today().isoformat()).strip()
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
                total_l = round(cant * costo, 2)
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
                flash("Proveedor y Nº documento son obligatorios", "danger")
            elif not lineas:
                flash("Agregue al menos un ítem", "danger")
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
                iva = round(neto * iva_pct / 100.0, 2)
                total = round(neto + iva, 2)
                try:
                    if row:
                        db.execute(
                            """
                            UPDATE facturas_compra SET documento=?, proveedor_id=?, concepto=?,
                            fecha_emision=?, fecha_vencimiento=?, neto=?, iva=?, total=?,
                            afecta_stock=?, notas=? WHERE id=?
                            """,
                            (
                                documento,
                                proveedor_id,
                                concepto,
                                fe,
                                fv,
                                neto,
                                iva,
                                total,
                                afecta_stock,
                                notas,
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
                            (documento, proveedor_id, concepto, fecha_emision, fecha_vencimiento,
                             neto, iva, total, pagado, saldo, estado, afecta_stock, notas, orden_compra_id)
                            VALUES (?,?,?,?,?,?,?,?,0,?,'pendiente',?,?,?)
                            """,
                            (
                                documento,
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
                    ops.recalc_factura_compra(db, fid_use)
                    if not row and afecta_stock:
                        ok, msg = ops.aplicar_entrada_compra(db, fid_use)
                        if not ok:
                            db.rollback()
                            flash(msg, "danger")
                            db.close()
                            return render_template(
                                "compras/form.html",
                                active="compras",
                                row=row,
                                items=items,
                                proveedores=proveedores,
                                productos=productos,
                                oc=oc,
                                ocs_disponibles=ocs_disp,
                                sugerido_documento=sugerido_documento,
                                hoy=date.today().isoformat(),
                            )
                    db.commit()
                    flash("Compra guardada" if row else "Compra emitida desde OC", "ok")
                    db.close()
                    return redirect(url_for("compras_detalle", fid=fid_use))
                except Exception as exc:
                    db.rollback()
                    flash(f"No se pudo guardar: {exc}", "danger")

        db.close()
        return render_template(
            "compras/form.html",
            active="compras",
            row=row,
            items=items,
            proveedores=proveedores,
            productos=productos,
            oc=oc,
            ocs_disponibles=ocs_disp,
            sugerido_documento=sugerido_documento,
            hoy=date.today().isoformat(),
        )

'''


def _replace_compras_form(text: str) -> str:
    start = text.find('    @app.route("/compras/nueva", methods=["GET", "POST"])')
    if start < 0:
        raise SystemExit("FAIL: compras/nueva route not found")
    end = text.find('    @app.route("/compras/<int:fid>")', start)
    if end < 0:
        raise SystemExit("FAIL: compras detalle route not found after form")
    return text[:start] + NEW_COMPRAS_FORM + "\n" + text[end:]


def _patch_oc_convertir() -> None:
    p = ROOT / "ops_oc_views.py"
    text = p.read_text(encoding="utf-8")
    old = '''    @app.route("/compras/ordenes/<int:oid>/convertir", methods=["POST"])
    @login_required
    def oc_convertir(oid: int):
        db = core.conn()
        ops.ensure_ops_schema(db)
        ops_oc.ensure_oc_schema(db)
        ok, res = ops_oc.convertir_oc_a_compra(db, oid)
        if not ok:
            db.close()
            flash(str(res), "danger")
            return redirect(url_for("oc_detalle", oid=oid))
        # alinear saldo/pagado
        ops.recalc_factura_compra(db, int(res))
        db.commit()
        db.close()
        flash("OC convertida en compra. Complete Nº documento fiscal si corresponde.", "ok")
        return redirect(url_for("compras_form", fid=int(res)))
'''
    new = '''    @app.route("/compras/ordenes/<int:oid>/convertir", methods=["GET", "POST"])
    @login_required
    def oc_convertir(oid: int):
        # Compat: emitir compra = formulario de compra linkeado a la OC
        return redirect(url_for("compras_form", oc=oid))
'''
    if "compras_form\", oc=oid)" in text or "compras_form', oc=oid)" in text:
        print("oc_convertir already redirects to compras_form?oc=")
        return
    if old in text:
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        print("OK ops_oc_views oc_convertir")
    else:
        # softer replace of function body
        m = re.search(
            r'    @app\.route\("/compras/ordenes/<int:oid>/convertir".*?def oc_convertir\(oid: int\):.*?(?=\n    @app\.route|\n\ndef |\Z)',
            text,
            re.S,
        )
        if not m:
            raise SystemExit("FAIL: oc_convertir not found")
        text = text[: m.start()] + new + text[m.end() :]
        p.write_text(text, encoding="utf-8")
        print("OK ops_oc_views oc_convertir (regex)")


def _copy_templates() -> None:
    for rel in (
        "templates/compras/form.html",
        "templates/compras/lista.html",
        "templates/compras/detalle.html",
        "templates/ordenes/detalle.html",
        "ops_oc.py",
    ):
        src = SRC / rel
        dst = ROOT / rel
        shutil.copy2(src, dst)
        print(f"OK {dst}")


def main() -> int:
    _copy_templates()
    ov = ROOT / "ops_views.py"
    text = ov.read_text(encoding="utf-8")
    if "Debe vincular la compra a una Orden de compra" in text:
        print("ops_views compras_form already requires OC")
    else:
        shutil.copy2(ov, ov.with_suffix(".py.bak_oc_link"))
        ov.write_text(_replace_compras_form(text), encoding="utf-8")
        print("OK ops_views compras_form OC-required")
    _patch_oc_convertir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
