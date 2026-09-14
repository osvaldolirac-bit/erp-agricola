#!/usr/bin/env python3
"""Reasigna gastos imputados en CC Cerezos → variedades El Espino por prorrateo administración.

- facturas *_P en Cerezos/CEREZOS → 3 filas por variedad (% prorrateo_cc)
- Elimina ppto/kg estimado legacy en Cerezos (mantiene variedades)
- NO toca movimientos bodega (ingresos ni salidas en Cerezos)

Uso:
  python3 scripts/reallocate_cerezos_costos_espino.py /root/espino/erp_espino.db
  python3 scripts/reallocate_cerezos_costos_espino.py /root/espino/erp_espino.db --apply
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LEGACY_CC = frozenset({"CEREZOS", "EL ESPINO"})

INSERT_COLS = (
    "nro_documento",
    "proveedor",
    "fecha_compra",
    "fecha_vencimiento",
    "monto_neto",
    "monto_total",
    "estado",
    "tipo",
    "metodo_pago",
    "fecha_pago",
    "concepto",
    "centro_costo",
    "monto_imputado",
    "razon_social",
    "tipo_gasto",
    "contratista_id",
    "monto_pagado",
    "banco",
    "folio_interno",
    "imputar_bruto",
)


def _is_legacy_cc(cc: str) -> bool:
    return (cc or "").strip().upper() in LEGACY_CC


def _load_prorrateo(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    rows = conn.execute(
        """SELECT centro_costo, porcentaje FROM prorrateo_cc
           WHERE porcentaje > 0 ORDER BY centro_costo"""
    ).fetchall()
    if rows:
        return [(str(r[0]), float(r[1]) / 100.0) for r in rows]
    from demo_web.services.espino_scope import prorrateo_pct_espino

    p = prorrateo_pct_espino()
    return [(k, v / 100.0) for k, v in sorted(p.items())]


def _split_amount(total: float, weights: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if total <= 0 or not weights:
        return []
    out: list[tuple[str, float]] = []
    rem = float(total)
    for i, (cc, w) in enumerate(weights):
        if i == len(weights) - 1:
            out.append((cc, round(rem, 6)))
        else:
            part = round(float(total) * w, 2)
            out.append((cc, part))
            rem -= part
    return out


def _row_dict(row: sqlite3.Row) -> dict:
    return {c: row[c] for c in row.keys()}


def plan_facturas(conn: sqlite3.Connection, weights: list[tuple[str, float]]) -> list[str]:
    lines: list[str] = []
    total_in = 0.0
    total_out = 0.0
    n = 0
    for row in conn.execute(
        """SELECT * FROM facturas
           WHERE nro_documento LIKE '%_P' AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')
           ORDER BY id"""
    ):
        d = _row_dict(row)
        monto = float(d.get("monto_imputado") or 0)
        total_in += monto
        n += 1
        parts = _split_amount(monto, weights)
        for cc, part in parts:
            total_out += part
        lines.append(
            f"SPLIT id={d['id']} {d['nro_documento']} {d.get('tipo_gasto','')} "
            f"${monto:,.0f} → " + ", ".join(f"{cc} ${p:,.2f}" for cc, p in parts)
        )
    lines.insert(0, f"facturas_P: {n} filas, total in=${total_in:,.2f}, total out=${total_out:,.2f}")
    return lines


def apply_facturas(conn: sqlite3.Connection, weights: list[tuple[str, float]]) -> int:
    n = 0
    for row in conn.execute(
        """SELECT * FROM facturas
           WHERE nro_documento LIKE '%_P' AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')
           ORDER BY id"""
    ):
        d = _row_dict(row)
        monto = float(d.get("monto_imputado") or 0)
        parts = _split_amount(monto, weights)
        conn.execute("DELETE FROM facturas WHERE id=?", (d["id"],))
        for cc, part in parts:
            if part <= 1e-9:
                continue
            vals = {k: d.get(k) for k in INSERT_COLS}
            vals["centro_costo"] = cc.upper()
            vals["monto_imputado"] = part
            placeholders = ",".join("?" * len(INSERT_COLS))
            conn.execute(
                f"INSERT INTO facturas ({','.join(INSERT_COLS)}) VALUES ({placeholders})",
                tuple(vals[c] for c in INSERT_COLS),
            )
        n += 1
    return n


def plan_cleanup(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    for tbl, col in (
        ("costos_ppto_temporada", "monto_ppto"),
        ("costos_kg_estimado_temporada", "kg_estimado"),
    ):
        for cc, val in conn.execute(
            f"""SELECT centro_costo, {col} FROM {tbl}
                WHERE UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')"""
        ):
            lines.append(f"DELETE {tbl}: {cc} = {val}")
    return lines


def apply_cleanup(conn: sqlite3.Connection) -> None:
    for tbl in ("costos_ppto_temporada", "costos_kg_estimado_temporada"):
        conn.execute(
            f"""DELETE FROM {tbl}
                WHERE UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')"""
        )


def verify(conn: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    n, t = conn.execute(
        """SELECT COUNT(*), COALESCE(SUM(monto_imputado),0) FROM facturas
           WHERE nro_documento LIKE '%_P' AND UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')"""
    ).fetchone()
    lines.append(f"facturas_P legacy Cerezos: {n} filas, ${float(t):,.2f}")
    for cc, cnt, tot in conn.execute(
        """SELECT centro_costo, COUNT(*), ROUND(SUM(monto_imputado),0) FROM facturas
           WHERE nro_documento LIKE '%_P' GROUP BY centro_costo ORDER BY 3 DESC"""
    ):
        lines.append(f"  {cc}: {cnt} filas, ${float(tot):,.0f}")
    for tbl in ("costos_ppto_temporada", "costos_kg_estimado_temporada"):
        rows = conn.execute(
            f"SELECT centro_costo FROM {tbl} WHERE UPPER(TRIM(centro_costo)) IN ('CEREZOS', 'EL ESPINO')"
        ).fetchall()
        lines.append(f"{tbl} legacy: {len(rows)} fila(s)")
    return lines


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    db = Path(sys.argv[1])
    do_apply = "--apply" in sys.argv
    if not db.is_file():
        raise SystemExit(f"No existe: {db}")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        weights = _load_prorrateo(conn)
        print("Prorrateo:", ", ".join(f"{cc} {w*100:.2f}%" for cc, w in weights))
        print()
        for line in plan_facturas(conn, weights):
            print(line)
        print()
        for line in plan_cleanup(conn):
            print(line)
        if do_apply:
            n = apply_facturas(conn, weights)
            apply_cleanup(conn)
            conn.commit()
            print(f"\n=== Aplicado: {n} facturas reasignadas ===")
            for line in verify(conn):
                print(line)
        else:
            print("\n=== Dry-run (use --apply) ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
