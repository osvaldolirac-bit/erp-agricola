#!/usr/bin/env python3
"""Reaplica prorrateo Consola a imputaciones _P de gastos operacionales en Compras.

Uso en VPS (La Concepción):
  cd /root/demo-web && ERP_APP=concepcion python3 scripts/reaplicar_prorrateo_gasto_compras.py --proveedor "Luis Aros"
  python3 scripts/reaplicar_prorrateo_gasto_compras.py --doc INT-20260830-01 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for extra in ("/root/demo-web", "/root"):
    if Path(extra).is_dir() and extra not in sys.path:
        sys.path.insert(0, extra)

os.environ.setdefault("ERP_APP", "concepcion")


def _neto_imputable(row) -> float:
    """Monto neto imputado a CC (respeta imputar_bruto si existe)."""
    keys = row.keys() if hasattr(row, "keys") else []
    monto_total = float(row["monto_total"] or 0)
    if "monto_neto" in keys and row["monto_neto"] not in (None, ""):
        try:
            mn = float(row["monto_neto"] or 0)
            if mn > 0:
                return mn
        except (TypeError, ValueError):
            pass
    imputar_bruto = 1
    if "imputar_bruto" in keys:
        try:
            imputar_bruto = int(row["imputar_bruto"] or 0)
        except (TypeError, ValueError):
            imputar_bruto = 1
    return monto_total if imputar_bruto else monto_total / 1.19


def main() -> int:
    parser = argparse.ArgumentParser(description="Reaplicar prorrateo CC en gastos Compras")
    parser.add_argument("--proveedor", help="Filtrar por proveedor (LIKE)")
    parser.add_argument("--doc", help="N° documento exacto (sin _P)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios")
    args = parser.parse_args()
    if not args.proveedor and not args.doc:
        parser.error("Indique --proveedor o --doc")

    from demo_web.services.erp_loader import get_erp_module_for
    from demo_web.services.native._helpers import reparto_imputacion_cc

    demo = get_erp_module_for("concepcion")
    conn = demo.conectar_db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
        extra = ", monto_neto" if "monto_neto" in cols else ""
        extra += ", imputar_bruto" if "imputar_bruto" in cols else ""
        if args.doc:
            parent = conn.execute(
                f"SELECT id, nro_documento, proveedor, monto_total{extra} "
                "FROM facturas WHERE nro_documento=? AND nro_documento NOT LIKE '%_P'",
                (args.doc.strip(),),
            ).fetchone()
        else:
            prov = args.proveedor.strip()
            parent = conn.execute(
                f"""SELECT id, nro_documento, proveedor, monto_total{extra}
                    FROM facturas
                    WHERE proveedor LIKE ?
                      AND nro_documento NOT LIKE '%_P'
                      AND nro_documento NOT LIKE '%_RRHH'
                      AND tipo IN ('Gasto Operacional', 'Gasto Vario')
                    ORDER BY fecha_compra DESC, id DESC LIMIT 1""",
                (f"%{prov}%",),
            ).fetchone()
        if not parent:
            print("No se encontró factura de gasto operacional.", file=sys.stderr)
            return 1

        doc = str(parent["nro_documento"])
        prov = str(parent["proveedor"])
        neto = _neto_imputable(parent)
        rows_p = conn.execute(
            """SELECT id, centro_costo, monto_imputado FROM facturas
               WHERE nro_documento=? AND proveedor=? ORDER BY centro_costo""",
            (doc + "_P", prov),
        ).fetchall()
        if not rows_p:
            print(f"Sin imputaciones _P para {doc} / {prov}", file=sys.stderr)
            return 1

        ccs = [str(r["centro_costo"]) for r in rows_p]
        reparto, err = reparto_imputacion_cc(demo, conn, neto, ccs)
        if err:
            print(f"Error prorrateo: {err}", file=sys.stderr)
            return 1

        reparto_map = {c.upper(): float(v) for c, v in reparto}
        print(f"Factura: {doc} | Proveedor: {prov} | Neto imputable: {neto:,.0f}")
        changed = 0
        for r in rows_p:
            cc = str(r["centro_costo"]).upper()
            old = float(r["monto_imputado"] or 0)
            new = reparto_map.get(cc, 0.0)
            print(f"  {cc}: {old:,.2f} -> {new:,.2f}")
            if abs(old - new) > 0.01:
                changed += 1
                if not args.dry_run:
                    conn.execute(
                        "UPDATE facturas SET monto_imputado=? WHERE id=?",
                        (new, r["id"]),
                    )
        if args.dry_run:
            print("DRY-RUN: no se guardaron cambios.")
            return 0
        if changed:
            conn.commit()
            demo.registrar_accion("COMPRA", f"Reaplicado prorrateo CC — {doc} — {prov}")
            print(f"OK — {changed} imputación(es) actualizada(s).")
        else:
            print("Sin cambios (ya estaba con prorrateo correcto).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
