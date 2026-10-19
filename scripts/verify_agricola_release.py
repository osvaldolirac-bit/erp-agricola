#!/usr/bin/env python3
"""Puerta de calidad agrícola LC+Espino (CI y pre-deploy).

  APP_ROOT=/workspace python3 scripts/verify_agricola_release.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[1]))


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)}).returncode


def verify_tenant_registry() -> int:
    sys.path.insert(0, str(ROOT))
    from demo_web.services.tenant_rules import verify_tenant_registry_errors

    errors = verify_tenant_registry_errors()
    if errors:
        print("FAIL tenant registry:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK  tenant registry (LC slugs + demo/globalgap)")
    return 0


def main() -> int:
    steps = [
        ([sys.executable, str(ROOT / "scripts/deploy_robustez_lc_espino_vps.py"), "--check"], "manifest+smoke"),
        ([sys.executable, str(ROOT / "scripts/smoke_robustez.py")], "smoke_robustez"),
        ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"], "unittest"),
    ]
    for cmd, label in steps:
        if _run(cmd) != 0:
            print(f"FAIL {label}", file=sys.stderr)
            return 1
    if verify_tenant_registry() != 0:
        return 1
    print("OK — verify_agricola_release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
