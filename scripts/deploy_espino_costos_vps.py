#!/usr/bin/env python3
"""Despliega migración costos Espino: tenant_scope + script reasignación."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    ("demo_web/services/tenant_scope.py", "demo_web/services/tenant_scope.py"),
    ("demo_web/services/espino_scope.py", "demo_web/services/espino_scope.py"),
    ("scripts/reallocate_cerezos_costos_espino.py", "scripts/reallocate_cerezos_costos_espino.py"),
    ("scripts/patch_espino_clasificar_cc.py", "scripts/patch_espino_clasificar_cc.py"),
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
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    run([*ssh_base, f"python3 {REMOTE}/scripts/patch_espino_clasificar_cc.py {REMOTE}/app_concepcion.py"])
    run([*ssh_base, "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"])
    print("OK — Espino costos CC desplegado.")


if __name__ == "__main__":
    main()
