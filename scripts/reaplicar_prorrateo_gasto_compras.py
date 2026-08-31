#!/usr/bin/env python3
"""Reaplica prorrateo Consola a imputaciones _P de gastos operacionales en Compras.

Uso en VPS (La Concepción):
  python3 scripts/reaplicar_prorrateo_gasto_compras.py --proveedor "Luis Aros"
  python3 scripts/reaplicar_prorrateo_gasto_compras.py --doc INT-20260830-01 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = os.environ.get("ERP_LC_DB", "/root/erp_concepcion_v6.db")

CUARTELES_PRORRATEO = [
    "CEREZOS CORTE 1",
    "CEREZOS CORTE 2",
    "CIRUELOS",
    "NOGALES APARICION",
    "NOGALES CRUZ DEL SUR",
]
CUARTELES_DIRECTOS = ["EL ESPINO", "OTROS"]
PRORRATEO_DEFAULT = {
    "CEREZOS CORTE 1": 7.94,
    "CEREZOS CORTE 2": 7.94,
    "CIRUELOS": 32.71,
    "NOGALES APARICION": 32.71,
    "NOGALES CRUZ DEL SUR": 18.70,
}


def _cargar_pesos(conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
        ).fetchall()
        if rows:
            return {str(r[0]).upper(): float(r[1]) / 100.0 for r in rows}
    except sqlite3.Error:
        pass
    return {k: v / 100.0 for k, v in PRORRATEO_DEFAULT.items()}


def reparto_por_cc(conn: sqlite3.Connection, total: float, seleccionados: list[str]) -> tuple[list[tuple[str, float]] | None, str | None]:
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return None, "Total inválido."
    if total_f <= 0:
        return None, "El total debe ser mayor a cero."

    sel = [str(c).strip().upper() for c in seleccionados if c]
    if not sel:
        return None, "Sin centros de costo."

    prorr = [c.upper() for c in CUARTELES_PRORRATEO]
    directos = [c.upper() for c in CUARTELES_DIRECTOS]
    invalid = [c for c in sel if c not in prorr and c not in directos]
    if invalid:
        return None, f"Centro de costo no válido: {invalid[0]}"

    dir_sel = [c for c in sel if c in directos]
    pr_sel = [c for c in sel if c in prorr]
    if dir_sel and pr_sel:
        return None, "No mezclar huertos del fundo con El Espino u Otros."
    if dir_sel:
        parte = total_f / len(dir_sel)
        return [(c, parte) for c in dir_sel], None

    pesos = _cargar_pesos(conn)
    sub = {c: float(pesos.get(c, 0.0) or 0.0) for c in pr_sel}
    suma = sum(sub.values())
    if suma <= 0:
        parte = total_f / len(pr_sel)
        return [(c, parte) for c in pr_sel], None
    return [(c, total_f * sub[c] / suma) for c in pr_sel], None


def _neto_imputable(row: sqlite3.Row, cols: set[str]) -> float:
    monto_total = float(row["monto_total"] or 0)
    if "monto_neto" in cols and row["monto_neto"] not in (None, ""):
        try:
            mn = float(row["monto_neto"] or 0)
            if mn > 0:
                return mn
        except (TypeError, ValueError):
            pass
    imputar_bruto = 1
    if "imputar_bruto" in cols:
        try:
            imputar_bruto = int(row["imputar_bruto"] or 0)
        except (TypeError, ValueError):
            imputar_bruto = 1
    return monto_total if imputar_bruto else monto_total / 1.19


def main() -> int:
    parser = argparse.ArgumentParser(description="Reaplicar prorrateo CC en gastos Compras")
    parser.add_argument("--proveedor", help="Filtrar por proveedor (LIKE)")
    parser.add_argument("--doc", help="N° documento exacto (sin _P)")
    parser.add_argument("--db", default=DB_PATH, help="Ruta BD LC")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios")
    args = parser.parse_args()
    if not args.proveedor and not args.doc:
        parser.error("Indique --proveedor o --doc")
    if not Path(args.db).is_file():
        print(f"BD no encontrada: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
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
        neto = _neto_imputable(parent, cols)
        rows_p = conn.execute(
            """SELECT id, centro_costo, monto_imputado FROM facturas
               WHERE nro_documento=? AND proveedor=? ORDER BY centro_costo""",
            (doc + "_P", prov),
        ).fetchall()
        if not rows_p:
            print(f"Sin imputaciones _P para {doc} / {prov}", file=sys.stderr)
            return 1

        ccs = [str(r["centro_costo"]) for r in rows_p]
        reparto, err = reparto_por_cc(conn, neto, ccs)
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
            print(f"OK — {changed} imputación(es) actualizada(s).")
        else:
            print("Sin cambios (ya estaba con prorrateo correcto).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
