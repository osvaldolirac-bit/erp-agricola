#!/usr/bin/env python3
"""Auditoría read-only: gastos varios con imputación en partes iguales vs prorrateo Consola."""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

DB = sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db"

PRORRATEO = {
    "CEREZOS CORTE 1": 7.94,
    "CEREZOS CORTE 2": 7.94,
    "CIRUELOS": 32.71,
    "NOGALES APARICION": 32.71,
    "NOGALES CRUZ DEL SUR": 18.70,
}
PRORR_SET = set(PRORRATEO)
DIRECTOS = {"EL ESPINO", "OTROS"}


def cargar_pesos(conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
        ).fetchall()
        if rows:
            return {str(r[0]).upper(): float(r[1]) for r in rows}
    except sqlite3.Error:
        pass
    return dict(PRORRATEO)


def neto(row: sqlite3.Row, cols: set[str]) -> float:
    mt = float(row["monto_total"] or 0)
    if "monto_neto" in cols and row["monto_neto"] not in (None, ""):
        try:
            mn = float(row["monto_neto"] or 0)
            if mn > 0:
                return mn
        except (TypeError, ValueError):
            pass
    ib = 1
    if "imputar_bruto" in cols:
        try:
            ib = int(row["imputar_bruto"] or 0)
        except (TypeError, ValueError):
            ib = 1
    return mt if ib else mt / 1.19


def esperado_prorrateo(pesos: dict[str, float], ccs: list[str], total: float) -> dict[str, float]:
    sub = {c: pesos.get(c, 0.0) for c in ccs}
    s = sum(sub.values())
    if s <= 0:
        p = total / len(ccs)
        return {c: p for c in ccs}
    return {c: total * sub[c] / s for c in ccs}


def main() -> int:
    if not Path(DB).is_file():
        print(f"BD no encontrada: {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
    extra = ", monto_neto" if "monto_neto" in cols else ""
    extra += ", imputar_bruto" if "imputar_bruto" in cols else ""

    pesos = cargar_pesos(conn)
    parents = conn.execute(
        f"""SELECT nro_documento, proveedor, fecha_compra, monto_total, concepto{extra}
            FROM facturas
            WHERE nro_documento NOT LIKE '%_P'
              AND nro_documento NOT LIKE '%_RRHH'
              AND tipo IN ('Gasto Operacional', 'Gasto Vario')
            ORDER BY fecha_compra DESC, id DESC"""
    ).fetchall()

    igual_bug = []
    ok_prorrateo = []
    otros = []

    for p in parents:
        doc = str(p["nro_documento"])
        prov = str(p["proveedor"])
        rows_p = conn.execute(
            """SELECT centro_costo, monto_imputado FROM facturas
               WHERE nro_documento=? AND proveedor=? ORDER BY centro_costo""",
            (doc + "_P", prov),
        ).fetchall()
        if len(rows_p) < 2:
            continue
        ccs = [str(r["centro_costo"]).upper() for r in rows_p]
        imps = [float(r["monto_imputado"] or 0) for r in rows_p]
        total_imp = sum(imps)
        n = len(imps)
        if n == 0 or total_imp <= 0:
            continue

        # ¿Partes iguales?
        avg = total_imp / n
        es_igual = all(abs(x - avg) < 0.02 for x in imps)

        prorr_ccs = [c for c in ccs if c in PRORR_SET]
        dir_ccs = [c for c in ccs if c in DIRECTOS]

        if len(prorr_ccs) >= 2 and not dir_ccs:
            exp = esperado_prorrateo(pesos, prorr_ccs, total_imp)
            max_desv = max(abs(imps[i] - exp.get(ccs[i], 0)) for i in range(n))
            item = {
                "doc": doc,
                "prov": prov,
                "fecha": str(p["fecha_compra"] or "")[:10],
                "neto": neto(p, cols),
                "total_imp": total_imp,
                "n_cc": n,
                "ccs": ccs,
                "imps": imps,
                "max_desv": max_desv,
                "concepto": (p["concepto"] or "")[:60],
            }
            if es_igual and max_desv > 1.0:
                igual_bug.append(item)
            elif max_desv <= 1.0:
                ok_prorrateo.append(item)
            else:
                otros.append(item)
        elif dir_ccs and es_igual:
            ok_prorrateo.append({"doc": doc, "prov": prov, "nota": "directos igual OK"})
        else:
            otros.append({"doc": doc, "prov": prov, "ccs": ccs, "imps": imps})

    print("=== AUDITORÍA GASTOS VARIOS — imputaciones multi-CC (La Concepción) ===\n")
    print(f"Pesos prorrateo Consola: {pesos}\n")
    print(f"CON BUG (partes iguales en huertos prorrateables): {len(igual_bug)}")
    for x in igual_bug:
        print(f"\n  Doc {x['doc']} | {x['prov']} | {x['fecha']} | neto ~{x['neto']:,.0f}")
        print(f"  Concepto: {x['concepto']}")
        for c, m in zip(x["ccs"], x["imps"]):
            pct_act = 100 * m / x["total_imp"] if x["total_imp"] else 0
            exp = esperado_prorrateo(pesos, x["ccs"], x["total_imp"]).get(c, 0)
            pct_exp = 100 * exp / x["total_imp"] if x["total_imp"] else 0
            print(f"    {c}: ${m:,.0f} ({pct_act:.1f}%) → debería ${exp:,.0f} ({pct_exp:.1f}%)")

    print(f"\n\nOK (prorrateo o directos): {len(ok_prorrateo)} facturas multi-CC")
    print(f"OTROS (mixtos / revisar manual): {len(otros)}")
    if otros[:5]:
        print("  Muestra otros:")
        for x in otros[:5]:
            print(f"    {x.get('doc')} {x.get('prov')} {x.get('ccs', x.get('nota', ''))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
