#!/usr/bin/env python3
"""Reaplica prorrateo Consola a TODAS las imputaciones _P erróneas (partes iguales).

Uso en VPS La Concepción:
  python3 scripts/reaplicar_prorrateo_gastos_batch.py --dry-run
  python3 scripts/reaplicar_prorrateo_gastos_batch.py
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
PRORR_SET = {c.upper() for c in CUARTELES_PRORRATEO}
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


def reparto_por_cc(conn: sqlite3.Connection, total: float, seleccionados: list[str]) -> tuple[dict[str, float] | None, str | None]:
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return None, "Total inválido."
    if total_f <= 0:
        return None, "Total inválido."

    sel = [str(c).strip().upper() for c in seleccionados if c]
    pr_sel = [c for c in sel if c in PRORR_SET]
    if len(pr_sel) < 2:
        return None, "Menos de 2 huertos prorrateables."

    pesos = _cargar_pesos(conn)
    sub = {c: float(pesos.get(c, 0.0) or 0.0) for c in pr_sel}
    suma = sum(sub.values())
    if suma <= 0:
        parte = total_f / len(pr_sel)
        return {c: parte for c in pr_sel}, None
    return {c: total_f * sub[c] / suma for c in pr_sel}, None


def _es_imputacion_igual_incorrecta(imps: dict[str, float], exp: dict[str, float]) -> bool:
    if len(imps) < 2:
        return False
    vals = list(imps.values())
    total = sum(vals)
    if total <= 0:
        return False
    avg = total / len(vals)
    es_igual = all(abs(v - avg) < 0.02 for v in vals)
    max_desv = max(abs(imps[c] - exp.get(c, 0)) for c in imps)
    return es_igual and max_desv > 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not Path(args.db).is_file():
        print(f"BD no encontrada: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        parents = conn.execute(
            """SELECT nro_documento, proveedor, fecha_compra FROM facturas
               WHERE nro_documento NOT LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
                 AND tipo IN ('Gasto Operacional', 'Gasto Vario')
               ORDER BY fecha_compra DESC, id DESC"""
        ).fetchall()

        fixed_docs = 0
        fixed_rows = 0
        skipped = 0

        for p in parents:
            doc = str(p["nro_documento"])
            prov = str(p["proveedor"])
            rows_p = conn.execute(
                """SELECT id, centro_costo, monto_imputado FROM facturas
                   WHERE nro_documento=? AND proveedor=? ORDER BY centro_costo""",
                (doc + "_P", prov),
            ).fetchall()
            if len(rows_p) < 2:
                continue
            imps = {str(r["centro_costo"]).upper(): float(r["monto_imputado"] or 0) for r in rows_p}
            ccs = list(imps.keys())
            if not all(c in PRORR_SET for c in ccs):
                continue
            total = sum(imps.values())
            exp, err = reparto_por_cc(conn, total, ccs)
            if err or not exp:
                continue
            if not _es_imputacion_igual_incorrecta(imps, exp):
                skipped += 1
                continue

            print(f"Corregir {doc} | {prov} | total imputado {total:,.0f}")
            doc_changed = 0
            for r in rows_p:
                cc = str(r["centro_costo"]).upper()
                old = float(r["monto_imputado"] or 0)
                new = exp.get(cc, 0.0)
                if abs(old - new) > 0.01:
                    doc_changed += 1
                    print(f"  {cc}: {old:,.2f} -> {new:,.2f}")
                    if not args.dry_run:
                        conn.execute(
                            "UPDATE facturas SET monto_imputado=? WHERE id=?",
                            (new, r["id"]),
                        )
            if doc_changed:
                fixed_docs += 1
                fixed_rows += doc_changed

        if args.dry_run:
            print(f"\nDRY-RUN: {fixed_docs} facturas / {fixed_rows} filas _P a corregir.")
            return 0
        if fixed_rows:
            conn.commit()
        print(f"\nOK — {fixed_docs} facturas, {fixed_rows} imputaciones actualizadas.")
        print(f"Omitidas (ya prorrateadas): {skipped}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
