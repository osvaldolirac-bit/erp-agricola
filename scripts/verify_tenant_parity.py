#!/usr/bin/env python3
"""Verificación paridad tenants LC (sin VPS — CI, pre-commit, pre-deploy).

Falla si las reglas documentadas en tenant_rules.py no coinciden con la implementación
o si los tests unitarios de paridad fallan.

Uso:
  APP_ROOT=/workspace python3 scripts/verify_tenant_parity.py
  python3 /root/scripts/verify_tenant_parity.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = Path(__file__).resolve().parent


def _ensure_path() -> None:
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def run_unit_tests() -> int:
    _ensure_path()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod_name in (
        "test_tenant_rules",
        "test_espino_tenant_rules",
        "test_tesoreria_proveedor_pago",
    ):
        path = SCRIPTS / f"{mod_name}.py"
        if not path.is_file():
            print(f"FAIL missing {path}", file=sys.stderr)
            return 1
        mod = loader.loadTestsFromName(mod_name.replace(".py", ""))
        suite.addTests(mod)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def verify_rules_module() -> int:
    _ensure_path()
    from demo_web.services.tenant_rules import verify_implementation_errors

    errors = verify_implementation_errors()
    if errors:
        print("FAIL tenant_rules parity:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK  tenant_rules parity (concepcion + espino)")
    return 0


def verify_tenants_py() -> int:
    _ensure_path()
    from demo_web.services.tenant_rules import LC_TENANT_SLUGS
    from demo_web.tenants import get_tenant

    for slug in LC_TENANT_SLUGS:
        t = get_tenant(slug)
        if not t:
            print(f"FAIL tenants.py sin entrada {slug}", file=sys.stderr)
            return 1
        if not t.get("db"):
            print(f"FAIL tenants.py {slug} sin db", file=sys.stderr)
            return 1
    print(f"OK  tenants.py LC slugs: {', '.join(sorted(LC_TENANT_SLUGS))}")
    return 0


def main() -> int:
    failed = 0
    for fn, label in (
        (verify_tenants_py, "registry"),
        (verify_rules_module, "rules"),
        (run_unit_tests, "unit tests"),
    ):
        print(f"--- {label} ---")
        if fn() != 0:
            failed += 1
    if failed:
        print(f"\n{failed} bloque(s) fallaron — no desplegar", file=sys.stderr)
        return 1
    print("\nAll tenant parity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
