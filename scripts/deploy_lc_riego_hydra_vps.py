#!/usr/bin/env python3
"""Despliega Riego LC: pestañas HYDRA + control Hydra + fixes link/cola."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HOST = os.environ.get("HOST", "45.7.230.70")
PORT = os.environ.get("PORT", "40484")
REMOTE = os.environ.get("REMOTE", "/root/demo-web")
ROOT = Path(__file__).resolve().parents[1]
SSH_TARGET = f"root@{HOST}"

FILES = [
    "demo_web/services/native/riego.py",
    "demo_web/services/hydrawise_riego.py",
    "demo_web/blueprints/registro_riego.py",
    "demo_web/templates/modules/riego.html",
    "demo_web/templates/partials/riego_hydrawise.html",
    "demo_web/templates/partials/_hydra_control_panel_styles.html",
    "demo_web/templates/registro_riego/hydra_link.html",
    "demo_web/templates/registro_riego/_hydra_scope_fields.html",
    "demo_web/templates/registro_riego/_hydra_control_ui.html",
    "demo_web/templates/registro_riego/_hydra_panel_control.html",
    "demo_web/templates/registro_riego/_hydra_panel_regar.html",
    "demo_web/templates/registro_riego/_hydra_panel_programar.html",
    "demo_web/templates/registro_riego/_hydra_cola_panel.html",
    "demo_web/templates/registro_riego/_hydra_cola_actions.html",
    "demo_web/templates/registro_riego/_hydra_fert_en_linea.html",
    "demo_web/templates/registro_riego/_hydra_fert_row_template.html",
    "demo_web/templates/registro_riego/_hydra_running_detail_modal.html",
    "demo_web/static/js/hydra_link_control.js",
    "demo_web/static/js/hydra_link_refresh.js",
    "demo_web/static/js/hydra_link_timer.js",
    "demo_web/static/js/hydra_link_running_detail.js",
    "scripts/hydrawise_cola_tick.py",
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def main() -> int:
    scp_base = ["scp", "-o", "StrictHostKeyChecking=no", "-P", PORT]
    ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", PORT, SSH_TARGET]
    if os.environ.get("SSHPASS"):
        scp_base = ["sshpass", "-e", *scp_base]
        ssh_base = ["sshpass", "-e", *ssh_base]
    else:
        print(
            "Falta SSHPASS (contraseña root VPS). Exporte SSHPASS y reintente.",
            file=sys.stderr,
        )
        return 1

    for rel in FILES:
        local = ROOT / rel
        if not local.is_file():
            print(f"Falta archivo local: {local}", file=sys.stderr)
            return 1
        run([*scp_base, str(local), f"{SSH_TARGET}:{REMOTE}/{rel}"])

    run(
        [
            *ssh_base,
            f"cd {REMOTE} && "
            "install -D scripts/hydrawise_cola_tick.py scripts/hydrawise_cola_tick.py 2>/dev/null; "
            "systemctl restart erp-agricola-web && systemctl is-active erp-agricola-web",
        ]
    )
    print("OK — Riego HYDRA LC desplegado en VPS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
