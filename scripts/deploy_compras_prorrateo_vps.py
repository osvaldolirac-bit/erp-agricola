#!/usr/bin/env python3
"""Despliega prorrateo Consola en Compras gastos + corrige Luis Aros (VPS LC)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"
FILES = [
    ("demo_web/services/native/_helpers.py", "demo_web/services/native/_helpers.py"),
    ("demo_web/services/native/compras.py", "demo_web/services/native/compras.py"),
    ("scripts/reaplicar_prorrateo_gasto_compras.py", "scripts/reaplicar_prorrateo_gasto_compras.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd[:6]), "..." if len(cmd) > 6 else "")
    subprocess.run(cmd, check=True)


def main() -> None:
    if not os.environ.get("SSHPASS"):
        print("SSHPASS no configurado.", file=sys.stderr)
        raise SystemExit(1)
    root = Path(__file__).resolve().parents[1]
    scp_base = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])
    ssh_base = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    remote_cmd = (
        f"cd {REMOTE} && "
        "grep -q reparto_imputacion_cc demo_web/services/native/_helpers.py && "
        "grep -q reparto_imputacion_cc demo_web/services/native/compras.py && "
        "ERP_APP=concepcion python3 scripts/reaplicar_prorrateo_gasto_compras.py --proveedor 'Luis Aros' && "
        "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web"
    )
    run([*ssh_base, remote_cmd])
    print("OK — Prorrateo compras desplegado y Luis Aros corregido.")


if __name__ == "__main__":
    main()
