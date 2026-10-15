#!/usr/bin/env python3
"""Falla si falta la UI de kardex en bodega.html (regresión frecuente en deploys parciales)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BODEGA_TPL = ROOT / "demo_web/templates/modules/bodega.html"
REQUIRED = (
    "sec_activa == 'kardex'",
    "sec='kardex', pid=row.id",
    "Cuenta corriente bodega",
)


def main() -> int:
    if not BODEGA_TPL.is_file():
        print(f"Falta {BODEGA_TPL}", file=sys.stderr)
        return 1
    text = BODEGA_TPL.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED if s not in text]
    if missing:
        print("Kardex UI incompleta en bodega.html:", ", ".join(missing), file=sys.stderr)
        return 1
    kardex_py = ROOT / "demo_web/services/bodega_kardex.py"
    compras_py = ROOT / "demo_web/services/espino_compras_kardex.py"
    for p in (kardex_py, compras_py):
        if not p.is_file():
            print(f"Falta {p}", file=sys.stderr)
            return 1
    print("OK — kardex bodega LC (UI + servicios) verificado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
