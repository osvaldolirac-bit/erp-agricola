#!/usr/bin/env python3
"""Diagnóstico y reparo coherencia bruto/neto facturas gasto El Espino.

Corrige:
- imputar_bruto en cabecera e imputaciones _P
- CC legacy (CEREZOS, CIRUELOS, EL ESPINO) → variedad operativa

Uso:
  python3 scripts/fix_imputar_bruto_espino.py /root/espino/erp_espino.db
  python3 scripts/fix_imputar_bruto_espino.py /root/espino/erp_espino.db --proveedor Ramos --apply
  python3 scripts/fix_imputar_bruto_espino.py /root/espino/erp_espino.db --apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_web.services.espino_scope import VARIEDADES_ESPINO

IVA = 1.19
LEGACY_CC = frozenset({"CEREZOS", "CIRUELOS", "EL ESPINO", "CEREZOS CORTE 1", "CEREZOS CORTE 2"})


def _ensure_col(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facturas)").fetchall()}
    if "imputar_bruto" not in cols:
        conn.execute("ALTER TABLE facturas ADD COLUMN imputar_bruto INTEGER DEFAULT 1")


def _infer_imputar_bruto(bruto: float, sum_imp: float) -> int:
    if bruto <= 0 or sum_imp <= 0:
        return 1
    if abs(sum_imp - bruto) < max(0.02, bruto * 0.005):
        return 1
    if abs(sum_imp * IVA - bruto) < max(0.02, bruto * 0.005):
        return 0
    return 1


def _neto_esperado(bruto: float, imputar_bruto: int) -> float:
    return bruto if imputar_bruto else bruto / IVA


def buscar_facturas(conn: sqlite3.Connection, proveedor: str | None) -> list[sqlite3.Row]:
    sql = """
        SELECT par.id, par.nro_documento, par.proveedor, par.fecha_compra,
               par.monto_total, COALESCE(par.imputar_bruto, 1) AS imputar_bruto,
               COALESCE(par.monto_neto, 0) AS monto_neto,
               COALESCE(SUM(p.monto_imputado), 0) AS sum_imp,
               GROUP_CONCAT(DISTINCT p.centro_costo) AS ccs
        FROM facturas par
        LEFT JOIN facturas p
          ON p.nro_documento = par.nro_documento || '_P'
         AND p.proveedor = par.proveedor
        WHERE par.nro_documento NOT LIKE '%_P'
          AND par.nro_documento NOT LIKE '%_RRHH'
          AND COALESCE(par.tipo, '') IN ('Gasto Operacional', 'Gasto Vario')
          AND par.monto_total > 0
    """
    params: list = []
    if proveedor:
        sql += " AND par.proveedor LIKE ?"
        params.append(f"%{proveedor}%")
    sql += " GROUP BY par.id ORDER BY par.id DESC"
    return conn.execute(sql, params).fetchall()


def plan_reparo(conn: sqlite3.Connection, proveedor: str | None) -> list[str]:
    lines: list[str] = []
    for row in buscar_facturas(conn, proveedor):
        bruto = float(row["monto_total"] or 0)
        sum_imp = float(row["sum_imp"] or 0)
        flag = int(row["imputar_bruto"] or 1)
        infer = _infer_imputar_bruto(bruto, sum_imp)
        neto = _neto_esperado(bruto, infer)
        ccs = (row["ccs"] or "").upper()
        legacy = any(lc in ccs for lc in LEGACY_CC)
        fixes: list[str] = []
        if flag != infer:
            fixes.append(f"imputar_bruto {flag}→{infer}")
        if legacy:
            fixes.append(f"CC legacy {row['ccs']}→{VARIEDADES_ESPINO[0]}")
        if abs(sum_imp - bruto) > 0.02 and abs(sum_imp * IVA - bruto) > 0.02 and sum_imp > 0:
            fixes.append(f"sum _P ${sum_imp:,.0f} no cuadra bruto ${bruto:,.0f}")
        status = "; ".join(fixes) if fixes else "OK"
        lines.append(
            f"id={row['id']} {row['nro_documento']} {row['proveedor']} "
            f"${bruto:,.0f} bruto | neto esp={neto:,.0f} | imp=${sum_imp:,.0f} | "
            f"CC={row['ccs'] or '—'} | {status}"
        )
    return lines


def aplicar(conn: sqlite3.Connection, proveedor: str | None) -> int:
    n = 0
    cc_destino = VARIEDADES_ESPINO[0].upper()
    for row in buscar_facturas(conn, proveedor):
        bruto = float(row["monto_total"] or 0)
        sum_imp = float(row["sum_imp"] or 0)
        infer = _infer_imputar_bruto(bruto, sum_imp)
        neto = _neto_esperado(bruto, infer)
        doc, prov = row["nro_documento"], row["proveedor"]
        conn.execute(
            "UPDATE facturas SET imputar_bruto=?, monto_neto=? WHERE id=?",
            (infer, neto, row["id"]),
        )
        conn.execute(
            """
            UPDATE facturas SET imputar_bruto=?
            WHERE nro_documento=? AND proveedor=?
            """,
            (infer, doc + "_P", prov),
        )
        for cc in LEGACY_CC:
            conn.execute(
                """
                UPDATE facturas SET centro_costo=?
                WHERE nro_documento=? AND proveedor=?
                  AND UPPER(TRIM(centro_costo))=?
                """,
                (cc_destino, doc + "_P", prov, cc),
            )
        n += 1
    return n


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    proveedor = None
    if "--proveedor" in sys.argv:
        i = sys.argv.index("--proveedor")
        if i + 1 < len(sys.argv):
            proveedor = sys.argv[i + 1]
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_col(conn)
        for line in plan_reparo(conn, proveedor):
            print(line)
        if do_apply:
            n = aplicar(conn, proveedor)
            conn.commit()
            print(f"\n=== Aplicado: {n} factura(s) ===")
        else:
            print("\n=== Dry-run (use --apply) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
