#!/usr/bin/env python3
"""Despliega en VPS demo-web: Tesorería INT-* + RRHH montos arbitrarios."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    # Tesorería LC — compras INT-* en pendientes
    "demo_web/services/tenant_rules.py",
    "demo_web/services/tenant_scope.py",
    "demo_web/services/tesoreria_cxp.py",
    "demo_web/services/lc_excluir_espino.py",
    "demo_web/services/native/tesoreria.py",
    # RRHH — montos sin step=1000
    "demo_web/templates/modules/rrhh.html",
    "demo_web/services/native/rrhh.py",
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
        f"python3 {REMOTE}/scripts/diagnostico_compras_tesoreria_lc.py "
        f"/root/erp_concepcion_v6.db --fecha 2026-09-22 --cc Huidobro",
    ])
    print("OK — Tesorería INT + RRHH montos desplegados.")


if __name__ == "__main__":
    main()
