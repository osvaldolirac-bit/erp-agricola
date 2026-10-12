#!/usr/bin/env python3
"""Correos/WhatsApp deben usar tenant_scope.nombre_erp, no demo.NOMBRE_ERP directo."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAIL_MODULES = (
    "demo_web/services/native/tesoreria.py",
    "demo_web/services/native/soporte.py",
    "demo_web/services/registro_riego.py",
    "demo_web/services/salida_petroleo.py",
    "demo_web/services/native/administracion.py",
)

FORBIDDEN = re.compile(r"\bdemo\.NOMBRE_ERP\b")


def main() -> int:
    errors: list[str] = []
    for rel in MAIL_MODULES:
        path = ROOT / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                errors.append(f"{rel}:{i}: {line.strip()}")
    if errors:
        print("Mail tenant branding check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print("Use: from demo_web.services.tenant_scope import nombre_erp", file=sys.stderr)
        return 1
    print("Mail tenant branding check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
