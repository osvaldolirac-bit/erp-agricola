#!/usr/bin/env python3
"""Comprueba que cada tenant tenga marca ERP distinta (regresión mail Tesorería)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_web.tenants import TENANTS, tenant_nombre_erp


def main() -> int:
    lc = tenant_nombre_erp(TENANTS["concepcion"])
    esp = tenant_nombre_erp(TENANTS["espino"])
    if lc == esp:
        print(f"FAIL: misma marca LC y Espino: {lc!r}", file=sys.stderr)
        return 1
    if "concepción" not in lc.lower() and "concepcion" not in lc.lower():
        print(f"FAIL: marca LC inesperada: {lc!r}", file=sys.stderr)
        return 1
    if "espino" not in esp.lower():
        print(f"FAIL: marca Espino inesperada: {esp!r}", file=sys.stderr)
        return 1
    print("OK", lc, "|", esp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
