#!/usr/bin/env python3
"""Despliega kardex/trazabilidad bodega LC en VPS (45.7.230.70)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    "demo_web/services/bodega_kardex.py",
    "demo_web/services/espino_compras_kardex.py",
    "demo_web/services/native/bodega.py",
    "demo_web/services/native/_helpers.py",
    "demo_web/templates/modules/bodega.html",
    "demo_web/templates/stock_bodega_rapido.html",
    "demo_web/services/native/bodega_stock_rapido.py",
]


def main() -> int:
    verify = ROOT / "scripts/verify_bodega_kardex_ui.py"
    if verify.is_file():
        subprocess.check_call([sys.executable, str(verify)])
    for rel in FILES:
        local = ROOT / rel
        if not local.is_file():
            print(f"Falta {local}", file=sys.stderr)
            return 1
        remote_path = f"{REMOTE}/{rel}"
        cmd = [
            "scp",
            "-P",
            PORT,
            "-o",
            "StrictHostKeyChecking=no",
            str(local),
            f"root@{HOST}:{remote_path}",
        ]
        print(">", " ".join(cmd))
        subprocess.check_call(cmd)
    restart = [
        "ssh",
        "-p",
        PORT,
        "-o",
        "StrictHostKeyChecking=no",
        f"root@{HOST}",
        "systemctl restart erp-agricola-web",
    ]
    print(">", " ".join(restart))
    subprocess.check_call(restart)
    print("OK — kardex bodega LC desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
