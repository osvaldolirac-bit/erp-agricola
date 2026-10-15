#!/usr/bin/env python3
"""Despliega kardex/trazabilidad bodega LC en VPS (45.7.230.70)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
SSH_TARGET = f"root@{HOST}"
FILES = [
    "demo_web/app.py",
    "demo_web/auth/public_urls.py",
    "demo_web/auth/routes.py",
    "demo_web/templates/login.html",
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
    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, SSH_TARGET]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
        ssh_base = ["sshpass", "-e", *ssh_base]
    else:
        print(
            "Falta SSHPASS (contraseña root VPS). Exporte SSHPASS y reintente.",
            file=sys.stderr,
        )
        return 1

    for rel in FILES:
        local = ROOT / rel
        if not local.is_file():
            print(f"Falta {local}", file=sys.stderr)
            return 1
        print("+", " ".join([*scp_base, str(local), f"{SSH_TARGET}:{REMOTE}/{rel}"]))
        subprocess.check_call([*scp_base, str(local), f"{SSH_TARGET}:{REMOTE}/{rel}"])
    print("+", " ".join([*ssh_base, "systemctl restart erp-agricola-web"]))
    subprocess.check_call([*ssh_base, "systemctl restart erp-agricola-web"])
    print("OK — kardex bodega LC + link público desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
