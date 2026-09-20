#!/usr/bin/env python3
"""Patch riomaipo app.py: PDF Vista 360 respeta orden en pantalla."""
from pathlib import Path

APP = Path("/root/riomaipo/rmweb/app.py")
text = APP.read_text()

old_load = '''def _load_vista360(db, cid: int | None):
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cli = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    cuentas = []
    abonos = []
    cots = []
    deuda = 0.0
    if cid:
        rows = db.execute(
            """
            SELECT cu.*, cot.folio AS cot_folio
            FROM cuentas cu
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY cu.id DESC
            """,
            (cid,),
        ).fetchall()
        cuentas = []
        for r in rows:
            d = dict(r)
            doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
            d["doc_display"] = doc_disp
            d["factura_display"] = fac_disp
            cuentas.append(d)
        deuda = sum(float(x["saldo"] or 0) for x in cuentas)
        abono_rows = db.execute(
            """
            SELECT a.fecha, a.monto, a.medio, a.nota,
                   cu.documento, cu.num_factura, cu.cotizacion_id,
                   cot.folio AS cot_folio
            FROM abonos a
            JOIN cuentas cu ON cu.id=a.cuenta_id
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(a.fecha) DESC, a.id DESC
            """,
            (cid,),
        ).fetchall()
        abonos = []
        for r in abono_rows:
            d = dict(r)
            doc_disp, _fac = core.cuenta_doc_factura_display(d)
            d["documento"] = doc_disp
            abonos.append(d)
        cots = db.execute(
            """
            SELECT id, folio, fecha, estado, total,
                   COALESCE(titulo, asunto, proyecto,'') AS titulo
            FROM cotizaciones
            WHERE cliente_id=?
            ORDER BY COALESCE(fecha,'') DESC, id DESC
            """,
            (cid,),
        ).fetchall()
    return cli, cuentas, abonos, cots, deuda'''

new_load = '''def _reorder_by_ids(rows: list, ids_csv: str | None, *, id_key: str = "id") -> list:
    """Reordena filas según ids visibles en pantalla (csv). Sin ids válidos, conserva el orden."""
    if not rows or not ids_csv:
        return rows
    wanted: list[int] = []
    for part in str(ids_csv).split(","):
        part = part.strip()
        if part.isdigit():
            wanted.append(int(part))
    if not wanted:
        return rows
    by_id = {}
    for r in rows:
        try:
            by_id[int(r[id_key])] = r
        except (KeyError, TypeError, ValueError):
            continue
    ordered = [by_id[i] for i in wanted if i in by_id]
    seen = {i for i in wanted if i in by_id}
    for r in rows:
        try:
            rid = int(r[id_key])
        except (KeyError, TypeError, ValueError):
            ordered.append(r)
            continue
        if rid not in seen:
            ordered.append(r)
    return ordered


def _load_vista360(db, cid: int | None):
    core.scrub_import_labels(db)
    core.sync_cuenta_cotizacion_links(db)
    cli = db.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone() if cid else None
    cuentas = []
    abonos = []
    cots = []
    deuda = 0.0
    if cid:
        rows = db.execute(
            """
            SELECT cu.*, cot.folio AS cot_folio
            FROM cuentas cu
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(cu.fecha_emision) DESC, cu.id DESC
            """,
            (cid,),
        ).fetchall()
        cuentas = []
        for r in rows:
            d = dict(r)
            doc_disp, fac_disp = core.cuenta_doc_factura_display(d)
            d["doc_display"] = doc_disp
            d["factura_display"] = fac_disp
            cuentas.append(d)
        deuda = sum(float(x["saldo"] or 0) for x in cuentas)
        abono_rows = db.execute(
            """
            SELECT a.id, a.fecha, a.monto, a.medio, a.nota,
                   cu.documento, cu.num_factura, cu.cotizacion_id,
                   cot.folio AS cot_folio
            FROM abonos a
            JOIN cuentas cu ON cu.id=a.cuenta_id
            LEFT JOIN cotizaciones cot ON cot.id = cu.cotizacion_id
            WHERE cu.cliente_id=?
            ORDER BY date(a.fecha) DESC, a.id DESC
            """,
            (cid,),
        ).fetchall()
        abonos = []
        for r in abono_rows:
            d = dict(r)
            doc_disp, _fac = core.cuenta_doc_factura_display(d)
            d["documento"] = doc_disp
            abonos.append(d)
        cots = db.execute(
            """
            SELECT id, folio, fecha, estado, total,
                   COALESCE(titulo, asunto, proyecto,'') AS titulo
            FROM cotizaciones
            WHERE cliente_id=?
            ORDER BY COALESCE(fecha,'') DESC, id DESC
            """,
            (cid,),
        ).fetchall()
    return cli, cuentas, abonos, cots, deuda'''

if old_load not in text:
    raise SystemExit("old_load block not found")
text = text.replace(old_load, new_load, 1)

old_pdf = '''    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    if not cli:
        flash("Cliente no encontrado", "danger")
        return redirect(url_for("cuentas_360"))
    pdf = core.estado_cuenta_pdf_bytes(cli, cuentas, abonos, cots, deuda, empresa)'''

new_pdf = '''    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    # Orden = el de la pantalla al momento de generar (ids en querystring).
    cuentas = _reorder_by_ids(cuentas, request.args.get("cuenta_ids"))
    abonos = _reorder_by_ids(abonos, request.args.get("abono_ids"))
    cots = _reorder_by_ids(list(cots) if cots else [], request.args.get("cot_ids"))
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    if not cli:
        flash("Cliente no encontrado", "danger")
        return redirect(url_for("cuentas_360"))
    pdf = core.estado_cuenta_pdf_bytes(cli, cuentas, abonos, cots, deuda, empresa)'''

if old_pdf not in text:
    raise SystemExit("old_pdf block not found")
text = text.replace(old_pdf, new_pdf, 1)

old_det = '''    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? ORDER BY id",
        (cuenta_id,),
    ).fetchall()'''
new_det = '''    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? "
        "ORDER BY date(fecha) DESC, id DESC",
        (cuenta_id,),
    ).fetchall()'''
if old_det not in text:
    raise SystemExit("old_det block not found")
text = text.replace(old_det, new_det, 1)

APP.write_text(text)
print("app.py patched OK")
