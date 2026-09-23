#!/usr/bin/env python3
"""Diagnóstico: compras que no aparecen en Tesorería pendientes (La Concepción).

Uso en VPS:
  python3 scripts/diagnostico_compras_tesoreria_lc.py /root/erp_concepcion_v6.db
  python3 scripts/diagnostico_compras_tesoreria_lc.py /root/erp_concepcion_v6.db --fecha 2026-09-22 --cc Huidobro
  python3 scripts/diagnostico_compras_tesoreria_lc.py /root/erp_concepcion_v6.db --fix-estado
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _motivos(row: dict) -> list[str]:
    motivos: list[str] = []
    nro = (row.get("nro_documento") or "").strip().upper()
    estado = (row.get("estado") or "").strip()
    monto = float(row.get("monto_total") or 0)
    pagado = float(row.get("monto_pagado") or 0)
    razon = (row.get("razon_social") or "").strip()

    if nro.endswith("_P"):
        motivos.append("Es fila de imputación _P (no aparece en Tesorería; debe verse el documento padre)")
    if nro.startswith("GE-"):
        motivos.append("Documento GE-* histórico de Costos (excluido de Tesorería)")
    if nro.startswith("INT-"):
        motivos.append(
            "Documento INT-* (gasto sin factura). Si no aparece, revisar filtro tesoreria_cxp "
            "(debe incluir INT en tenant concepcion)"
        )
    if estado != "Pendiente":
        motivos.append(f"estado={estado!r} (debe ser Pendiente)")
    if monto <= 0:
        motivos.append("monto_total <= 0")
    if monto - pagado <= 0.01:
        motivos.append(f"saldo <= 0 (monto_pagado={pagado})")
    if razon.casefold() == "el espino":
        motivos.append("razon_social=El Espino (excluida en tenant La Concepción)")
    if not motivos:
        motivos.append("Debería aparecer en Tesorería tras desplegar fix INT-*")
    return motivos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path, help="Ruta erp_concepcion_v6.db")
    ap.add_argument("--fecha", default="2026-09-22", help="Fecha compra YYYY-MM-DD")
    ap.add_argument("--cc", default="Huidobro", help="Filtro centro de costo / concepto / proveedor")
    ap.add_argument("--fix-estado", action="store_true", help="Restaurar Pagado→Pendiente si monto_pagado=0")
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"ERROR: no existe {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    like = f"%{args.cc}%"

    rows = conn.execute(
        """
        SELECT f.id, f.nro_documento, f.proveedor, f.fecha_compra, f.monto_total,
               COALESCE(f.monto_pagado, 0) AS monto_pagado, f.estado, f.razon_social,
               f.concepto,
               GROUP_CONCAT(DISTINCT p.centro_costo) AS centros
        FROM facturas f
        LEFT JOIN facturas p
          ON p.nro_documento = f.nro_documento || '_P' AND p.proveedor = f.proveedor
        WHERE f.fecha_compra = ?
          AND f.nro_documento NOT LIKE '%_P'
          AND (
            f.concepto LIKE ? OR f.proveedor LIKE ?
            OR p.centro_costo LIKE ?
          )
        GROUP BY f.id
        ORDER BY f.id
        """,
        (args.fecha, like, like, like),
    ).fetchall()

    if not rows:
        print(f"Sin facturas padre en {args.fecha} que coincidan con {args.cc!r}")
        return 0

    fixed = 0
    for r in rows:
        d = dict(r)
        print("—" * 60)
        print(
            f"ID {d['id']} | {d['nro_documento']} | {d['proveedor']} | "
            f"${d['monto_total']:,.0f} | {d['estado']} | CC: {d.get('centros') or '-'}"
        )
        print(f"  Concepto: {d.get('concepto') or ''}")
        for m in _motivos(d):
            print(f"  • {m}")
        if args.fix_estado and d["estado"] == "Pagado" and float(d["monto_pagado"] or 0) <= 0.01:
            conn.execute(
                "UPDATE facturas SET estado='Pendiente', monto_pagado=0 WHERE id=?",
                (d["id"],),
            )
            fixed += 1
            print("  → Corregido: estado Pendiente, monto_pagado=0")

    if fixed:
        conn.commit()
        print(f"\n{fixed} documento(s) corregido(s).")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
