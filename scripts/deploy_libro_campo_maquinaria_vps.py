#!/usr/bin/env python3
"""Despliega fix maquinaria Libro de Campo tenant El Espino."""
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
    (ROOT / "erp_maquinaria.py", f"{DEMO_WEB}/erp_maquinaria.py"),
    (ROOT / "demo_web/services/native/libro_campo.py", f"{DEMO_WEB}/demo_web/services/native/libro_campo.py"),
    (ROOT / "demo_web/services/native/administracion.py", f"{DEMO_WEB}/demo_web/services/native/administracion.py"),
    (ROOT / "demo_web/services/native/espino_libro_campo.py", f"{DEMO_WEB}/demo_web/services/native/espino_libro_campo.py"),
    (ROOT / "scripts/sync_espino_maquinaria.py", f"{SCRIPTS}/sync_espino_maquinaria.py"),
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
                f"python3 {SCRIPTS}/sync_espino_maquinaria.py && "
                f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q "
                f"erp_maquinaria.py demo_web/services/native/libro_campo.py "
                f"demo_web/services/native/administracion.py "
                f"demo_web/services/native/espino_libro_campo.py && "
                "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
            ),
        ]
    )
    print("OK — Libro de Campo maquinaria Espino desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
