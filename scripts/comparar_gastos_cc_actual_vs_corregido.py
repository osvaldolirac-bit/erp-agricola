#!/usr/bin/env python3
"""Compara gastos varios imputados por CC: actual vs corregido (read-only)."""
from __future__ import annotations

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
ALL_CC = list(PRORRATEO) + ["EL ESPINO", "OTROS"]


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


def esperado(pesos: dict[str, float], ccs: list[str], total: float) -> dict[str, float]:
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
    pesos = cargar_pesos(conn)

    actual = {c: 0.0 for c in ALL_CC}
    corregido_delta = {c: 0.0 for c in ALL_CC}
    n_bug = 0

    parents = conn.execute(
        """SELECT nro_documento, proveedor FROM facturas
           WHERE nro_documento NOT LIKE '%_P' AND nro_documento NOT LIKE '%_RRHH'
             AND tipo IN ('Gasto Operacional', 'Gasto Vario')"""
    ).fetchall()

    for p in parents:
        doc = str(p["nro_documento"])
        prov = str(p["proveedor"])
        rows_p = conn.execute(
            """SELECT centro_costo, monto_imputado FROM facturas
               WHERE nro_documento=? AND proveedor=?""",
            (doc + "_P", prov),
        ).fetchall()
        if not rows_p:
            continue
        ccs = [str(r["centro_costo"]).upper() for r in rows_p]
        imps = {ccs[i]: float(rows_p[i]["monto_imputado"] or 0) for i in range(len(rows_p))}
        for c, m in imps.items():
            if c in actual:
                actual[c] += m

        if len(rows_p) < 2:
            continue
        prorr_ccs = [c for c in ccs if c in PRORR_SET]
        dir_ccs = [c for c in ccs if c in DIRECTOS]
        if len(prorr_ccs) < 2 or dir_ccs:
            continue
        total_imp = sum(imps.values())
        if total_imp <= 0:
            continue
        n = len(imps)
        avg = total_imp / n
        es_igual = all(abs(imps[c] - avg) < 0.02 for c in ccs)
        exp = esperado(pesos, prorr_ccs, total_imp)
        max_desv = max(abs(imps[c] - exp.get(c, 0)) for c in ccs)
        if es_igual and max_desv > 1.0:
            n_bug += 1
            for c in ccs:
                if c in corregido_delta:
                    corregido_delta[c] += exp.get(c, 0) - imps[c]

    print("=== GASTOS VARIOS IMPUTADOS POR CC — La Concepción ===\n")
    print(f"Facturas con imputación incorrecta incluidas en delta: {n_bug}\n")
    print(f"{'Centro de costo':<28} {'Actual':>16} {'Corregido':>16} {'Delta':>16}")
    print("-" * 78)
    tot_a = tot_c = tot_d = 0.0
    for c in ALL_CC:
        a = actual[c]
        d = corregido_delta[c]
        c_new = a + d
        tot_a += a
        tot_c += c_new
        tot_d += d
        sign = "+" if d >= 0 else ""
        print(f"{c:<28} ${a:>14,.0f} ${c_new:>14,.0f} {sign}${d:>14,.0f}")
    print("-" * 78)
    print(f"{'TOTAL':<28} ${tot_a:>14,.0f} ${tot_c:>14,.0f} ${tot_d:>14,.0f}")
    print("\nNota: Actual = suma de todas las filas _P (gastos operacionales).")
    print("Corregido = actual + ajuste solo en las facturas con reparto 1/N erróneo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
