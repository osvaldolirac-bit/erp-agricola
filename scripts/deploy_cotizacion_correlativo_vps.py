#!/usr/bin/env python3
"""Despliega fix correlativo cotizaciones Río Maipo + renombra COT-1019."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/riomaipo"
FILES = [
    ("riomaipo_vps/rmweb/core.py", "rmweb/core.py"),
    ("riomaipo_vps/rmweb/app.py", "rmweb/app.py"),
    ("scripts/fix_cotizacion_folio_1019.py", "scripts/fix_cotizacion_folio_1019.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd[:8]), "...")
    subprocess.run(cmd, check=True)


def main() -> None:
    if not os.environ.get("SSHPASS"):
        raise SystemExit("SSHPASS no configurado")
    root = Path(__file__).resolve().parents[1]
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        run([*scp, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    run(
        [
            *ssh,
            f"mkdir -p {REMOTE}/scripts && "
            f"grep -q next_cotizacion_folio {REMOTE}/rmweb/core.py && "
            f"python3 {REMOTE}/scripts/fix_cotizacion_folio_1019.py && "
            f"systemctl restart erp-riomaipo && systemctl is-active erp-riomaipo",
        ]
    )
    print("OK — correlativo cotizaciones desplegado.")


if __name__ == "__main__":
    main()
