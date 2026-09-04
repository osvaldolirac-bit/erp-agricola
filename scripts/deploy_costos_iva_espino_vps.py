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
LOCAL_FILES = [
    (ROOT / "demo-web/app_concepcion.py", f"{DEMO_WEB}/app_concepcion.py"),
    (ROOT / "demo_web/services/native/costos.py", f"{DEMO_WEB}/demo_web/services/native/costos.py"),
    (ROOT / "demo_web/templates/modules/costos.html", f"{DEMO_WEB}/demo_web/templates/modules/costos.html"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not os.environ.get("SSHPASS"):
        print("Defina SSHPASS", file=sys.stderr)
        return 1
    for local, remote in LOCAL_FILES:
        if not local.is_file():
            print(f"MISSING {local}", file=sys.stderr)
            return 1
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    for local, remote in LOCAL_FILES:
        run([*scp, str(local), f"{HOST}:{remote}"])
    compile_targets = " ".join(
        p.replace(f"{DEMO_WEB}/", "") for _, p in LOCAL_FILES if p.endswith(".py")
    )
    run(
        [
            *ssh,
            f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q {compile_targets} && "
            "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    print("OK — costos neto/bruto Espino desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
