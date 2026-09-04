#!/usr/bin/env python3
"""Despliega correos tenant-aware + invitación clave auto en VPS."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
DEMO_WEB = "/root/demo-web"
ERP_MASTER = "/root/erp_master"
SCRIPTS = "/root/scripts"

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "erp_correo_html.py", f"{DEMO_WEB}/erp_correo_html.py"),
    (ROOT / "demo-web/app_concepcion.py", f"{DEMO_WEB}/app_concepcion.py"),
    (ROOT / "demo_web/services/erp_loader.py", f"{DEMO_WEB}/demo_web/services/erp_loader.py"),
    (ROOT / "demo_web/services/native/administracion.py", f"{DEMO_WEB}/demo_web/services/native/administracion.py"),
    (ROOT / "erp_master/erp_master/tenant_admin.py", f"{ERP_MASTER}/erp_master/tenant_admin.py"),
    (ROOT / "erp_master/erp_master/app.py", f"{ERP_MASTER}/erp_master/app.py"),
    (
        ROOT / "erp_master/erp_master/templates/super_consola.html",
        f"{ERP_MASTER}/erp_master/templates/super_consola.html",
    ),
    (ROOT / "scripts/reenviar_invitacion_tenant.py", f"{SCRIPTS}/reenviar_invitacion_tenant.py"),
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
                f"cd {DEMO_WEB} && .venv/bin/python3 -m compileall -q "
                f"erp_correo_html.py app_concepcion.py demo_web/services/erp_loader.py "
                f"demo_web/services/native/administracion.py && "
                f"cd {ERP_MASTER} && python3 -m compileall -q erp_master/tenant_admin.py erp_master/app.py && "
                "systemctl restart erp-agricola-web erp-master-web && "
                "systemctl is-active erp-agricola-web erp-master-web"
            ),
        ]
    )
    print("OK — mail/invitación tenant desplegado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
