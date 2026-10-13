#!/usr/bin/env python3
"""Despliega contadores sidebar Petróleo / Maquinaria / Riego en VPS demo-web."""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/demo-web")
WS = Path(__file__).resolve().parents[2]

FILES = [
    ("demo_web/services/sidebar_badges.py", ROOT / "demo_web/services/sidebar_badges.py"),
    ("demo_web/auth/decorators.py", ROOT / "demo_web/auth/decorators.py"),
    ("demo_web/services/salida_petroleo.py", ROOT / "demo_web/services/salida_petroleo.py"),
    ("demo_web/services/registro_riego.py", ROOT / "demo_web/services/registro_riego.py"),
    ("erp_maquinaria.py", ROOT / "erp_maquinaria.py"),
    ("demo-web/app_concepcion.py", ROOT / "app_concepcion.py"),
]


def main() -> int:
    if not ROOT.is_dir():
        print(f"ERROR: no existe {ROOT}", file=sys.stderr)
        return 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for rel, dst in FILES:
        src = WS / rel
        if not src.is_file():
            print(f"ERROR: falta fuente {src}", file=sys.stderr)
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file():
            bak = dst.with_suffix(dst.suffix + f".bak.{ts}")
            shutil.copy2(dst, bak)
            print(f"Backup: {bak}")
        shutil.copy2(src, dst)
        print(f"OK: {dst}")
    print("Reiniciar: systemctl restart erp-agricola-web erp-lc-web erp-demo-web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
