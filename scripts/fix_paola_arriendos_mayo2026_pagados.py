#!/usr/bin/env python3
"""Marca arriendos María Paola may-2026 como Pagado (ya cancelados en campo)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo-web"))
os.environ.setdefault("ERP_DB", sys.argv[1] if len(sys.argv) > 1 else "/root/erp_concepcion_v6.db")

import app_concepcion as app  # noqa: E402


def main() -> int:
    conn = app.conectar_db()
    try:
        before = conn.execute(
            """
            SELECT nro_documento, monto_total, estado
            FROM facturas
            WHERE nro_documento NOT LIKE '%_P'
              AND fecha_compra BETWEEN '2026-05-01' AND '2026-05-31'
              AND (
                UPPER(COALESCE(proveedor, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%PAOLA%'
              )
            ORDER BY monto_total DESC
            """
        ).fetchall()
        print("=== Antes ===")
        for r in before:
            print(r)

        conn.execute(
            "DELETE FROM schema_meta WHERE clave='paola_arriendos_mayo2026_pagados_v1'"
        )
        conn.commit()
        app._migrar_arriendos_paola_mayo2026_pagados(conn)

        after = conn.execute(
            """
            SELECT nro_documento, monto_total, estado, monto_pagado
            FROM facturas
            WHERE nro_documento NOT LIKE '%_P'
              AND fecha_compra BETWEEN '2026-05-01' AND '2026-05-31'
              AND (
                UPPER(COALESCE(proveedor, '')) LIKE '%PAOLA%'
                OR UPPER(COALESCE(concepto, '')) LIKE '%PAOLA%'
              )
            ORDER BY monto_total DESC
            """
        ).fetchall()
        print("\n=== Después ===")
        for r in after:
            print(r)

        pend = conn.execute(
            """
            SELECT COALESCE(SUM(
              MAX(0, monto_total - COALESCE(monto_pagado, 0))
            ), 0)
            FROM facturas
            WHERE estado='Pendiente' AND nro_documento NOT LIKE '%_P' AND monto_total > 0
              AND UPPER(TRIM(nro_documento)) NOT GLOB 'INT-*'
              AND UPPER(TRIM(nro_documento)) NOT GLOB 'GE-*'
            """
        ).fetchone()[0]
        print(f"\nDeuda CxP pendiente (sin INT-/GE-): ${float(pend):,.0f}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
