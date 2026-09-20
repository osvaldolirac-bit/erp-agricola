#!/usr/bin/env python3
"""Despliega ingrediente activo en Compras → Insumos (VPS demo-web)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    ("demo_web/services/native/compras.py", "demo_web/services/native/compras.py"),
    ("demo_web/templates/modules/compras.html", "demo_web/templates/modules/compras.html"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    if not os.environ.get("SSHPASS"):
        print("SSHPASS no configurado. En el VPS ejecute:", file=sys.stderr)
        print("  bash /root/scripts/apply_compras_insumo_ia_on_vps.sh", file=sys.stderr)
        raise SystemExit(1)
    root = Path(__file__).resolve().parents[1]
    scp_base = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    ssh_base = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    run(
        [
            *ssh_base,
            "grep -q ingrediente_activo /root/demo-web/demo_web/templates/modules/compras.html "
            "&& systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    print("OK — Compras insumo IA desplegado.")


if __name__ == "__main__":
    main()
