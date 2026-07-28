#!/usr/bin/env python3
"""Patch Río Maipo /comercial Dashboard: deuda y vencimientos de Tesorería (CxP)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
APP = ROOT / "app.py"
CSS = ROOT / "static" / "css" / "app.css"
DASH_TMPL = ROOT / "templates" / "dashboard.html"
SRC_TMPL = Path(__file__).resolve().parents[1] / "rmweb" / "templates" / "dashboard.html"

OLD_DASHBOARD = '''@app.route("/")
@login_required
def dashboard():
    db = core.conn()
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
    )
'''

NEW_DASHBOARD = '''@app.route("/")
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
'''

OLD_CSS = """.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .65rem;
  margin-bottom: 1rem;
}"""

NEW_CSS = """.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .65rem;
  margin-bottom: 1rem;
}
.kpi-grid.kpi-grid-6 {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}
a.kpi { display: block; color: #fff; }
a.kpi:hover { color: #fff; filter: brightness(1.05); }"""


def main() -> int:
    text = APP.read_text(encoding="utf-8")
    if "vencimientos_cxp" in text and "kpis_cxp" in text and "Saldo por pagar" in DASH_TMPL.read_text(encoding="utf-8"):
        print("already patched")
        return 0
    if OLD_DASHBOARD not in text:
        raise SystemExit("FAIL: dashboard() block not found in app.py")
    bak = APP.with_suffix(APP.suffix + f".bak_dash_teso")
    shutil.copy2(APP, bak)
    APP.write_text(text.replace(OLD_DASHBOARD, NEW_DASHBOARD, 1), encoding="utf-8")
    print(f"OK app.py (backup {bak.name})")

    css = CSS.read_text(encoding="utf-8")
    if "kpi-grid-6" not in css:
        if OLD_CSS not in css:
            raise SystemExit("FAIL: .kpi-grid block not found in app.css")
        shutil.copy2(CSS, CSS.with_suffix(CSS.suffix + ".bak_dash_teso"))
        CSS.write_text(css.replace(OLD_CSS, NEW_CSS, 1), encoding="utf-8")
        print("OK app.css")
    else:
        print("app.css already has kpi-grid-6")

    if not SRC_TMPL.exists():
        raise SystemExit(f"FAIL: template source missing: {SRC_TMPL}")
    shutil.copy2(DASH_TMPL, DASH_TMPL.with_suffix(".html.bak_dash_teso"))
    shutil.copy2(SRC_TMPL, DASH_TMPL)
    print(f"OK dashboard.html from {SRC_TMPL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
