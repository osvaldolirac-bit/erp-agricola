#!/usr/bin/env python3
"""Despliega fix imputaciones Costos El Espino + restaura BD legacy CEREZOS."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = os.environ.get("ESPINO_VPS", "root@45.7.230.70")
PORT = os.environ.get("ESPINO_SSH_PORT", "40484")
REMOTE_WEB = os.environ.get("ESPINO_REMOTE_WEB", "/root/demo-web")
REMOTE_DB = os.environ.get("ESPINO_DB", "/root/espino/erp_espino.db")

FILES = [
    "demo_web/tenants.py",
    "demo_web/services/erp_loader.py",
    "demo_web/services/erp_compat.py",
    "demo_web/services/espino_scope.py",
    "demo_web/services/espino_costos.py",
    "demo_web/services/tenant_scope.py",
    "demo_web/services/lc_excluir_espino.py",
    "demo_web/services/dashboard.py",
    "demo_web/services/native/costos.py",
    "scripts/patch_costos_cc_canon.py",
    "scripts/verify_espino_costos_parity.py",
]


def _ssh(cmd: str) -> None:
    base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, REMOTE, cmd]
    if os.environ.get("SSHPASS"):
        subprocess.run(["sshpass", "-e", "ssh", *base[1:]], check=True, env=os.environ)
    else:
        subprocess.run(base, check=True)


def _scp(local: Path, remote_path: str) -> None:
    dest = f"{REMOTE}:{remote_path}"
    base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT, str(local), dest]
    if os.environ.get("SSHPASS"):
        subprocess.run(["sshpass", "-e", "scp", *base[1:]], check=True, env=os.environ)
    else:
        subprocess.run(base, check=True)


def main() -> int:
    for rel in FILES:
        local = ROOT / rel
        if not local.is_file():
            print(f"Falta archivo local: {local}", file=sys.stderr)
            return 1
        remote = f"{REMOTE_WEB}/{rel}"
        _scp(local, remote)
        print("OK", rel)

    app = f"{REMOTE_WEB}/app_concepcion.py"
    _ssh(f"python3 {REMOTE_WEB}/scripts/patch_costos_cc_canon.py {app} || true")
    _ssh(f"python3 {REMOTE_WEB}/scripts/verify_espino_costos_parity.py espino")
    _ssh("systemctl restart erp-agricola-web 2>/dev/null || systemctl restart gunicorn 2>/dev/null || true")
    print("Deploy completado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
