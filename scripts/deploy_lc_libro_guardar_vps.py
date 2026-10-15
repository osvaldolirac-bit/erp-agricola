#!/usr/bin/env python3
"""Despliega fix Libro de Campo LC (guardar evento + rebaja bodega)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ("demo_web/services/native/libro_campo.py", "demo_web/services/native/libro_campo.py"),
    ("demo_web/services/native/bodega.py", "demo_web/services/native/bodega.py"),
    ("demo_web/services/libro_campo_gap.py", "demo_web/services/libro_campo_gap.py"),
    ("demo_web/templates/modules/libro_campo.html", "demo_web/templates/modules/libro_campo.html"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def main() -> int:
    ssh_base = ["ssh", "-p", PORT, HOST]
    for local_rel, remote_rel in FILES:
        local = ROOT / local_rel
        if not local.is_file():
            print(f"Falta {local}", file=sys.stderr)
            return 1
        run(["scp", "-P", PORT, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    run(
        [
            *ssh_base,
            f"cd {REMOTE} && systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
