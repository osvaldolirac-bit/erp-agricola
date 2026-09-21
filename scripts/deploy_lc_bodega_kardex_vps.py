#!/usr/bin/env python3
"""Despliega kardex bodega La Concepción en VPS demo-web."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    ("demo_web/services/bodega_kardex.py", "demo_web/services/bodega_kardex.py"),
    ("demo_web/services/espino_compras_kardex.py", "demo_web/services/espino_compras_kardex.py"),
    ("demo_web/services/native/bodega.py", "demo_web/services/native/bodega.py"),
    ("demo_web/templates/modules/bodega.html", "demo_web/templates/modules/bodega.html"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    if os.environ.get("SSHPASS"):
        ssh_base = ["sshpass", "-e", *ssh_base]
    run([*ssh_base, "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"])
    print("OK — LC bodega kardex desplegado.")


if __name__ == "__main__":
    main()
