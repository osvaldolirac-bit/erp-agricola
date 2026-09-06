#!/usr/bin/env python3
"""Despliega logo tenant El Espino (dashboard, sidebar, PDFs) en VPS."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
DEMO_WEB = "/root/demo-web"
STATIC = "/root/static"
SCRIPTS = "/root/scripts"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "demo_web/static/img/logo_espino.png", f"{DEMO_WEB}/demo_web/static/img/logo_espino.png"),
    (ROOT / "demo_web/static/img/logo_espino.jpg", f"{DEMO_WEB}/demo_web/static/img/logo_espino.jpg"),
    (ROOT / "demo_web/static/img/logo_espino.jpeg", f"{DEMO_WEB}/demo_web/static/img/logo_espino.jpeg"),
    (ROOT / "demo_web/static/img/logo_espino.svg", f"{DEMO_WEB}/demo_web/static/img/logo_espino.svg"),
    (ROOT / "scripts/bootstrap_espino_logo.py", f"{SCRIPTS}/bootstrap_espino_logo.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not os.environ.get("SSHPASS"):
        print("Defina SSHPASS", file=sys.stderr)
        return 1

    sources = [local for local, _ in FILES if local.is_file()]
    if not sources:
        print(
            "ERROR: falta demo_web/static/img/logo_espino.png (o jpg/svg) en el repo.",
            file=sys.stderr,
        )
        return 1

    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]

    for local, remote in FILES:
        if not local.is_file():
            continue
        run([*scp, str(local), f"{HOST}:{remote}"])

    run(
        [
            *ssh,
            (
                f"python3 {SCRIPTS}/bootstrap_espino_logo.py --force && "
                f"test -f {STATIC}/logo_espino.png && "
                f"systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
            ),
        ]
    )
    print("OK — logo El Espino desplegado (UI + PDFs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
