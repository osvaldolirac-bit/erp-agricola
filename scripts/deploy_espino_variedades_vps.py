#!/usr/bin/env python3
"""Despliega variedades Espino (LC + consola prorrateo) en VPS."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE_DEMO = "/root/demo-web"
REMOTE_MASTER = "/root/erp_master"

DEMO_FILES = [
    "demo_web/services/espino_scope.py",
    "demo_web/services/erp_loader.py",
    "demo_web/tenants.py",
    "demo_web/services/native/espino_libro_campo.py",
    "demo_web/templates/partials/espino_libro_campo.html",
    "demo_web/services/libro_campo_gap.py",
]

MASTER_FILES = [
    ("erp_master/erp_master/tenant_admin.py", "erp_master/tenant_admin.py"),
    ("erp_master/erp_master/config.py", "erp_master/config.py"),
    ("erp_master/erp_master/app.py", "erp_master/app.py"),
]
MASTER_TEMPLATE_FILES = [
    "super_consola.html",
    "_base_app.html",
    "_sidebar.html",
    "home.html",
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _scp_base() -> list[str]:
    base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    if os.environ.get("SSHPASS"):
        return ["sshpass", "-e", *base]
    return base


def _ssh_base() -> list[str]:
    base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, HOST]
    if os.environ.get("SSHPASS"):
        return ["sshpass", "-e", *base]
    return base


def scp_files(root: Path, files: list[str] | list[tuple[str, str]], remote_root: str) -> None:
    for item in files:
        if isinstance(item, tuple):
            local_rel, remote_rel = item
        else:
            local_rel = remote_rel = item
        local = root / local_rel
        if not local.is_file():
            raise SystemExit(f"Falta archivo local: {local}")
        run([*_scp_base(), str(local), f"{HOST}:{remote_root}/{remote_rel}"])


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print("=== Deploy variedades Espino ===")
    scp_files(root, DEMO_FILES, REMOTE_DEMO)
    scp_files(root, MASTER_FILES, REMOTE_MASTER)
    for tpl in MASTER_TEMPLATE_FILES:
        local = root / "erp_master" / "erp_master" / "templates" / tpl
        if not local.is_file():
            raise SystemExit(f"Falta plantilla consola: {local}")
        run(
            [
                *_scp_base(),
                str(local),
                f"{HOST}:{REMOTE_MASTER}/erp_master/templates/{tpl}",
            ]
        )
    remote_cmd = (
        "systemctl restart erp-agricola-web erp-master-web && "
        "systemctl is-active erp-agricola-web erp-master-web && "
        "(test -f /root/scripts/verify_consola.py && python3 /root/scripts/verify_consola.py || "
        "curl -sf http://127.0.0.1:8507/health | grep -q ok)"
    )
    run([*_ssh_base(), remote_cmd])
    print("OK — variedades Espino desplegadas. Configure prorrateo en Super Consola → El Espino.")


if __name__ == "__main__":
    main()
