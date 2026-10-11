#!/usr/bin/env python3
"""Despliega módulo Hydra (Hydrawise) — solo archivos LC / riego."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = "root@45.7.230.70"
PORT = "40484"
REMOTE = "/root/demo-web"

FILES = [
    ("demo_web/services/hydrawise_client.py", "demo_web/services/hydrawise_client.py"),
    ("demo_web/services/hydrawise_riego.py", "demo_web/services/hydrawise_riego.py"),
    ("demo_web/services/registro_riego.py", "demo_web/services/registro_riego.py"),
    ("demo_web/blueprints/registro_riego.py", "demo_web/blueprints/registro_riego.py"),
    ("demo_web/templates/registro_riego/form.html", "demo_web/templates/registro_riego/form.html"),
    ("demo_web/services/native/riego.py", "demo_web/services/native/riego.py"),
    ("demo_web/services/native/administracion.py", "demo_web/services/native/administracion.py"),
    ("demo_web/templates/modules/riego.html", "demo_web/templates/modules/riego.html"),
    ("demo_web/templates/partials/riego_hydrawise.html", "demo_web/templates/partials/riego_hydrawise.html"),
    ("demo_web/templates/modules/administracion.html", "demo_web/templates/modules/administracion.html"),
    ("demo_web/services/tenant_scope.py", "demo_web/services/tenant_scope.py"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    run([sys.executable, str(root / "scripts" / "test_hydrawise_module.py")])

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
            "\"from demo_web.services.hydrawise_riego import hydrawise_habilitado; "
            "from demo_web.services.hydrawise_client import flatten_relays; print('hydra-import-ok')\" "
            "&& systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    verify = root / "scripts" / "verify_hydra_cc_mapeo.py"
    if verify.is_file():
        run([*scp_base, str(verify), f"{HOST}:{REMOTE}/scripts/verify_hydra_cc_mapeo.py"])
        run(
            [
                *ssh_base,
                f"cd {REMOTE} && PYTHONPATH={REMOTE} ERP_LC_DB=/root/erp_concepcion_v6.db "
                ".venv/bin/python3 scripts/verify_hydra_cc_mapeo.py",
            ]
        )
    print("OK — Hydra LC desplegado en VPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
