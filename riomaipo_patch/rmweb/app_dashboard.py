# Excerpt synced from VPS /root/riomaipo/rmweb/app.py — dashboard()
@app.route("/")
@login_required
def dashboard():
    from rmweb import ops as _ops

    db = core.conn()
    _ops.ensure_ops_schema(db)
    cotas = db.execute(
        "SELECT estado, COUNT(*) n, COALESCE(SUM(total),0) t FROM cotizaciones GROUP BY estado"
    ).fetchall()
    n_cot = sum(r["n"] for r in cotas)
    sum_cot = sum(float(r["t"]) for r in cotas)
    n_apr = sum(r["n"] for r in cotas if r["estado"] == "aprobada")
    saldo = db.execute("SELECT COALESCE(SUM(saldo),0) s FROM cuentas").fetchone()["s"]
    pend = db.execute(
        "SELECT COUNT(*) n FROM cuentas WHERE saldo > 0"
    ).fetchone()["n"]
    venc = db.execute(
        """
        SELECT COUNT(*) n FROM cuentas
        WHERE saldo > 0 AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < date('now')
        """
    ).fetchone()["n"]
    top = db.execute(
        """
        SELECT cl.razon_social, COALESCE(SUM(cu.saldo),0) saldo
        FROM cuentas cu LEFT JOIN clientes cl ON cl.id=cu.cliente_id
        GROUP BY cu.cliente_id
        HAVING saldo > 0
        ORDER BY saldo DESC LIMIT 8
        """
    ).fetchall()

    # Tesorería (CxP): misma base que /tesoreria/
    kpis_cxp = _ops.kpis_cxp(db)
    venc_cxp_row = db.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(saldo),0) m
        FROM facturas_compra
        WHERE COALESCE(saldo,0) > 0.009
          AND fecha_vencimiento IS NOT NULL
          AND fecha_vencimiento < date('now')
        """
    ).fetchone()
    venc_cxp = int(venc_cxp_row["n"] or 0)
    venc_cxp_monto = float(venc_cxp_row["m"] or 0)
    vencimientos_cxp = db.execute(
        """
        SELECT f.id, f.documento, f.fecha_vencimiento, f.saldo, f.estado,
               p.razon_social AS proveedor,
               CASE
                 WHEN f.fecha_vencimiento IS NOT NULL
                      AND f.fecha_vencimiento < date('now') THEN 1
                 ELSE 0
               END AS vencido
        FROM facturas_compra f
        LEFT JOIN proveedores p ON p.id=f.proveedor_id
        WHERE COALESCE(f.saldo,0) > 0.009
        ORDER BY COALESCE(f.fecha_vencimiento, f.fecha_emision) ASC, f.id
        LIMIT 12
        """
    ).fetchall()
    top_prov = db.execute(
        """
        SELECT COALESCE(p.razon_social, '—') AS proveedor,
               COALESCE(SUM(f.saldo),0) AS saldo
        FROM facturas_compra f
        LEFT JOIN proveedores p ON p.id=f.proveedor_id
        WHERE COALESCE(f.saldo,0) > 0.009
        GROUP BY f.proveedor_id
        HAVING saldo > 0
        ORDER BY saldo DESC
        LIMIT 8
        """
    ).fetchall()

    db.close()
    return render_template(
        "dashboard.html",
        active="dashboard",
        n_cot=n_cot,
        sum_cot=sum_cot,
        n_apr=n_apr,
        saldo=saldo,
        pend=pend,
        venc=venc,
        top=top,
        cotas=cotas,
        kpis_cxp=kpis_cxp,
        venc_cxp=venc_cxp,
        venc_cxp_monto=venc_cxp_monto,
        vencimientos_cxp=vencimientos_cxp,
        top_prov=top_prov,
    )

