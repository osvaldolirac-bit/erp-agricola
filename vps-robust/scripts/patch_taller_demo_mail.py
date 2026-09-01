#!/usr/bin/env python3
"""VPS: textos de mail OTP/invitación por tenant (taller vs comercial) + probar multi-tenant."""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "riomaipo_vps" / "rmweb"
VPS_ROOT = Path("/root/riomaipo/rmweb")

FILES = ("demo_invitacion.py", "app.py")


def main() -> int:
    if not VPS_ROOT.is_dir():
        print(f"ERROR: no existe {VPS_ROOT}", file=sys.stderr)
        return 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in FILES:
        src = SRC_ROOT / name
        dst = VPS_ROOT / name
        if not src.is_file():
            print(f"ERROR: falta fuente {src}", file=sys.stderr)
            return 1
        if dst.is_file():
            bak = dst.with_suffix(dst.suffix + f".bak.{ts}")
            shutil.copy2(dst, bak)
            print(f"Backup: {bak}")
        shutil.copy2(src, dst)
        print(f"Desplegado: {dst}")
    print("OK — reinicie erp-riomaipo: systemctl restart erp-riomaipo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
