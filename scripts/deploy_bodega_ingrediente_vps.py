#!/usr/bin/env python3
"""Despliega fix parseo decimal bodega (ingrediente activo / corregir stock)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
DEMO_WEB = "/root/demo-web"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "demo_web/services/native/_helpers.py", f"{DEMO_WEB}/demo_web/services/native/_helpers.py"),
    (ROOT / "demo_web/services/native/bodega.py", f"{DEMO_WEB}/demo_web/services/native/bodega.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not os.environ.get("SSHPASS"):
        print("Defina SSHPASS con la clave del VPS.", file=sys.stderr)
        return 1
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    for local, remote in FILES:
        if not local.is_file():
            print(f"MISSING: {local}", file=sys.stderr)
            return 1
        run([*scp, str(local), f"{HOST}:{remote}"])
    run(
        [
            *ssh,
            (
                f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q "
                f"demo_web/services/native/_helpers.py demo_web/services/native/bodega.py && "
                "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
            ),
        ]
    )
    print("OK — bodega ingrediente/stock desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
