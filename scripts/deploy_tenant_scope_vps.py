#!/usr/bin/env python3
"""Despliega capa tenant_scope (marca ERP, loader) sin tocar lógica Espino/LC específica."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"

FILES = [
    ("demo_web/tenants.py", "demo_web/tenants.py"),
    ("demo_web/services/erp_loader.py", "demo_web/services/erp_loader.py"),
    ("demo_web/services/tenant_scope.py", "demo_web/services/tenant_scope.py"),
    ("demo_web/services/native/tesoreria.py", "demo_web/services/native/tesoreria.py"),
    ("demo_web/services/native/compras.py", "demo_web/services/native/compras.py"),
    ("demo_web/services/native/soporte.py", "demo_web/services/native/soporte.py"),
    ("demo_web/services/native/administracion.py", "demo_web/services/native/administracion.py"),
    ("demo_web/services/registro_riego.py", "demo_web/services/registro_riego.py"),
    ("demo_web/services/salida_petroleo.py", "demo_web/services/salida_petroleo.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    for script in ("test_tenant_nombre_erp.py", "check_mail_tenant_branding.py", "check_espino_tenant_purity.py"):
        run([sys.executable, str(root / "scripts" / script)])

    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
    for local_rel, remote_rel in FILES:
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*scp_base, str(local), f"{HOST}:{REMOTE}/{remote_rel}"])

    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    if os.environ.get("SSHPASS"):
        ssh_base = ["sshpass", "-e", *ssh_base]
    run(
        [
            *ssh_base,
            f"cd {REMOTE} && PYTHONPATH={REMOTE} .venv/bin/python3 -c "
            "'from demo_web.tenants import TENANTS, tenant_nombre_erp; "
            "print(tenant_nombre_erp(TENANTS[\"concepcion\"]), \"|\", tenant_nombre_erp(TENANTS[\"espino\"]))' "
            "&& systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    print("OK — tenant_scope desplegado en VPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
