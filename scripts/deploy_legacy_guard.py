"""Bloquea deploys parciales legacy salvo ERP_DEPLOY_LEGACY_OK=1."""
from __future__ import annotations

import os
import sys
from pathlib import Path

CANONICAL = "scripts/deploy_robustez_lc_espino_vps.py"


def block_legacy_deploy(caller: str | Path) -> None:
    if os.environ.get("ERP_DEPLOY_LEGACY_OK") == "1":
        print(f"WARN: deploy legacy {Path(caller).name} (ERP_DEPLOY_LEGACY_OK=1)", file=sys.stderr)
        return
    print(
        f"\nBLOCKED: {Path(caller).name}\n"
        f"  Use: python3 {CANONICAL} [--check]\n"
        f"  Política: .cursor/rules/erp-agricola-vps-deploy.mdc\n"
        f"  Excepción: ERP_DEPLOY_LEGACY_OK=1\n",
        file=sys.stderr,
    )
    raise SystemExit(2)
