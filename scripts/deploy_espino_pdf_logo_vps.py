#!/usr/bin/env python3
"""Despliega fix logos PDF El Espino en VPS."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
DEMO_WEB = "/root/demo-web"
SCRIPTS = "/root/scripts"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "demo_web/services/branding.py", f"{DEMO_WEB}/demo_web/services/branding.py"),
    (ROOT / "demo-web/app_concepcion.py", f"{DEMO_WEB}/app_concepcion.py"),
    (ROOT / "demo-web/erp_petroleo_planilla.py", f"{DEMO_WEB}/erp_petroleo_planilla.py"),
    (ROOT / "scripts/bootstrap_espino_logo.py", f"{SCRIPTS}/bootstrap_espino_logo.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not os.environ.get("SSHPASS"):
        print("Defina SSHPASS", file=sys.stderr)
        return 1
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    for local, remote in FILES:
        if not local.is_file():
            print(f"MISSING {local}", file=sys.stderr)
            return 1
        run([*scp, str(local), f"{HOST}:{remote}"])
    run(
        [
            *ssh,
            (
                f"python3 {SCRIPTS}/bootstrap_espino_logo.py && "
                f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q "
                f"demo_web/services/branding.py app_concepcion.py erp_petroleo_planilla.py && "
                "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
            ),
        ]
    )
    print("OK — logos PDF Espino desplegados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
