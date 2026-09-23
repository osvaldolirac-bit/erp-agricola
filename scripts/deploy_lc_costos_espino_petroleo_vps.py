#!/usr/bin/env python3
"""Despliega fix Costos LC: EL ESPINO visible con salidas de petróleo."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    "demo_web/services/lc_excluir_espino.py",
    "demo_web/services/native/costos.py",
    "scripts/diagnostico_costos_espino_petroleo_lc.py",
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
        ssh_base = ["sshpass", "-e", *ssh_base]
    else:
        print("ERROR: export SSHPASS='...' requerido para desplegar.", file=sys.stderr)
        sys.exit(1)

    for rel in FILES:
        local = root / rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{rel}"])

    run([
        *ssh_base,
        "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
    ])
    run([
        *ssh_base,
        f"python3 {REMOTE}/scripts/diagnostico_costos_espino_petroleo_lc.py "
        f"/root/erp_concepcion_v6.db",
    ])
    print("OK — Costos EL ESPINO petróleo desplegado.")


if __name__ == "__main__":
    main()
