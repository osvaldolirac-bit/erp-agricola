#!/usr/bin/env python3
"""Crea salidas de bodega faltantes según Libro de Campo (tenant LC).

Uso en VPS:
  cp /root/erp_concepcion_v6.db /root/erp_concepcion_v6.db.bak-$(date +%Y%m%d-%H%M)
  python3 scripts/repair_lc_bodega_salidas_desde_libro_vps.py --db /root/erp_concepcion_v6.db
  python3 scripts/repair_lc_bodega_salidas_desde_libro_vps.py --db /root/erp_concepcion_v6.db --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_web.services.lc_bodega_desfase import (  # noqa: E402
    DEFAULT_VENTANA_DIAS,
    insertar_salida_desde_lc,
    listar_lc_sin_salida_bodega,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Reparar salidas bodega desde Libro de Campo (LC)")
    p.add_argument("--db", required=True, help="Ruta SQLite erp_concepcion_v6.db")
    p.add_argument("--apply", action="store_true", help="Ejecutar cambios (default: simulación)")
    p.add_argument("--desde", default="", help="Fecha inicio YYYY-MM-DD (default: hoy-365d)")
    p.add_argument("--hasta", default="", help="Fecha fin YYYY-MM-DD (default: hoy)")
    p.add_argument("--ventana", type=int, default=DEFAULT_VENTANA_DIAS)
    p.add_argument("--backup", action="store_true", help="Copia .bak antes de --apply")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERROR: no existe {db_path}", file=sys.stderr)
        return 1

    hoy = date.today()
    fi = date.fromisoformat(args.desde) if args.desde else hoy - timedelta(days=365)
    ff = date.fromisoformat(args.hasta) if args.hasta else hoy

    if args.apply and args.backup:
        bak = db_path.with_suffix(db_path.suffix + f".bak-repair-{hoy.isoformat()}")
        shutil.copy2(db_path, bak)
        print(f"Backup: {bak}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        lc_sin = listar_lc_sin_salida_bodega(conn, fi, ff, ventana_dias=args.ventana)
        print(f"Ventana LC↔bodega: {args.ventana} días · rango LC {fi} … {ff}")
        print(f"Líneas LC sin salida emparejable: {len(lc_sin)}")

        ok = skip = fail = 0
        for lc in lc_sin:
            res = insertar_salida_desde_lc(conn, lc, dry_run=not args.apply)
            if res.get("skipped"):
                skip += 1
                print(f"  SKIP dup App {lc['n_app']:05d} · {lc['producto']} · {lc['gasto']} · {lc['sector']}")
            elif res.get("ok") and res.get("dry_run"):
                ok += 1
                print(
                    f"  DRY  App {lc['n_app']:05d} · {lc['fecha']} · {lc['producto']} · "
                    f"{lc['gasto']} → {lc['sector']}"
                )
            elif res.get("ok"):
                ok += 1
                conn.commit()
                print(
                    f"  OK   mov_id={res.get('mov_id')} App {lc['n_app']:05d} · {lc['producto']} · "
                    f"{lc['gasto']} → {lc['sector']} ({lc['fecha']})"
                )
            else:
                fail += 1
                print(
                    f"  FAIL App {lc['n_app']:05d} · {lc['producto']} · {res.get('reason')} · "
                    f"stock={res.get('stock', '—')}"
                )

        if not args.apply:
            print("\nSimulación. Use --apply para insertar movimientos y descontar stock.")
        print(f"Resumen: ok={ok} skip={skip} fail={fail}")
    finally:
        conn.close()
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
