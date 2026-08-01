def _reorder_by_ids(rows: list, ids_csv: str | None, *, id_key: str = "id") -> list:
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
    return cli, cuentas, abonos, cots, deuda


@app.route("/cuentas/360")
@login_required
def cuentas_360():
    db = core.conn()
    clientes = db.execute(
        "SELECT id, razon_social FROM clientes WHERE activo=1 ORDER BY razon_social"
    ).fetchall()
    cid = request.args.get("cliente_id", type=int)
    if not cid and clientes:
        cid = clientes[0]["id"]
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    sum_abonos = sum(float(a["monto"] or 0) for a in abonos)
    db.close()
    return render_template(
        "cuentas/vista360.html",
        active="cuentas",
        clientes=clientes,
        cid=cid,
        cli=cli,
        cuentas=cuentas,
        abonos=abonos,
        sum_abonos=sum_abonos,
        cots=cots,
        deuda=deuda,
    )


@app.route("/cuentas/360/pdf")
@login_required
def cuentas_360_pdf():
    cid = request.args.get("cliente_id", type=int)
    db = core.conn()
    if not cid:
        flash("Selecciona un cliente", "danger")
        db.close()
        return redirect(url_for("cuentas_360"))
    cli, cuentas, abonos, cots, deuda = _load_vista360(db, cid)
    # Orden = el de la pantalla al momento de generar (ids en querystring).
    cuentas = _reorder_by_ids(cuentas, request.args.get("cuenta_ids"))
    abonos = _reorder_by_ids(abonos, request.args.get("abono_ids"))
    cots = _reorder_by_ids(list(cots) if cots else [], request.args.get("cot_ids"))
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
    if not cli:
        flash("Cliente no encontrado", "danger")
        return redirect(url_for("cuentas_360"))
    pdf = core.estado_cuenta_pdf_bytes(cli, cuentas, abonos, cots, deuda, empresa)
    safe = "".join(ch if ch.isalnum() else "_" for ch in (cli["razon_social"] or "cliente"))[:40]
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"estado_cuenta_{safe}.pdf",
        (cuenta_id,),
    ).fetchone()
    if not cuenta:
        db.close()
        flash("Documento no encontrado", "danger")
        return redirect(url_for("cuentas_list"))
    abonos = db.execute(
        "SELECT fecha, monto, medio, nota FROM abonos WHERE cuenta_id=? "
        "ORDER BY date(fecha) DESC, id DESC",
        (cuenta_id,),
    ).fetchall()
    empresa = db.execute("SELECT * FROM empresa WHERE id=1").fetchone()
    db.close()
