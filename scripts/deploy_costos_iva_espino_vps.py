#!/usr/bin/env python3
"""Despliega costos neto Espino (IVA 19% rebajado en rubros seleccionados)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
DEMO_WEB = "/root/demo-web"
ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "demo-web/app_concepcion.py"
REMOTE = f"{DEMO_WEB}/app_concepcion.py"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not os.environ.get("SSHPASS"):
        print("Defina SSHPASS", file=sys.stderr)
        return 1
    if not LOCAL.is_file():
        print(f"MISSING {LOCAL}", file=sys.stderr)
        return 1
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    run([*scp, str(LOCAL), f"{HOST}:{REMOTE}"])
    run(
        [
            *ssh,
            f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q app_concepcion.py && "
            "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    print("OK — costos neto Espino desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
