#!/usr/bin/env python3
"""Parche: _armar_matriz_costos_vista_b usa cc_canon (CEREZOS → Cerezos)."""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/demo-web/app_concepcion.py")

OLD = '''    matriz = {rubro: {c: 0.0 for c in cols} for rubro in RUBROS_MATRIZ_COSTOS}

    def add(cc, rubro, monto):
        cc_u = str(cc or "").upper().strip()
        if cc_u not in cuarteles or not rubro:
            return
        m = float(monto or 0)
        if abs(m) < 0.01:
            return
        matriz[rubro][cc_u] += m
        matriz[rubro]["TOTAL"] += m'''

NEW = '''    matriz = {rubro: {c: 0.0 for c in cols} for rubro in RUBROS_MATRIZ_COSTOS}
    cc_canon = {str(c).upper().strip(): c for c in cuarteles}

    def add(cc, rubro, monto):
        cc_key = cc_canon.get(str(cc or "").upper().strip())
        if not cc_key or not rubro:
            return
        m = float(monto or 0)
        if abs(m) < 0.01:
            return
        matriz[rubro][cc_key] += m
        matriz[rubro]["TOTAL"] += m'''


def main() -> int:
    text = APP.read_text(encoding="utf-8")
    if NEW.strip() in text:
        print("OK already patched:", APP)
        return 0
    if OLD not in text:
        print("ERROR: block not found in", APP, file=sys.stderr)
        return 1
    APP.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("Patched cc_canon in", APP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
