#!/usr/bin/env python3
"""Despliega fix de sesión/logout en ERP Comercial (/comercial)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path("/root/riomaipo")

FILES = [
    ("riomaipo_vps/rmweb/app.py", "rmweb/app.py"),
    ("riomaipo_vps/rmweb/templates/login.html", "rmweb/templates/login.html"),
    ("riomaipo_vps/rmweb/templates/base.html", "rmweb/templates/base.html"),
]


def main() -> None:
    for src_rel, dst_rel in FILES:
        src = REPO / src_rel
        dst = ROOT / dst_rel
        if not src.is_file():
            raise SystemExit(f"Missing source: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"copied {src_rel} -> {dst}")

    subprocess.run(["systemctl", "restart", "erp-riomaipo"], check=True)
    print("erp-riomaipo restarted")


if __name__ == "__main__":
    main()
