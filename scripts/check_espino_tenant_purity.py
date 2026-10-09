#!/usr/bin/env python3
"""Falla si módulos El Espino leen constantes globales del ERP Concepción sin tenant_scope."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Rutas donde aplica la regla (código operativo Espino en Flask).
GLOBS = (
    "demo_web/services/native/espino*.py",
    "demo_web/services/espino_*.py",
)

# Atributos del módulo ERP que no deben usarse en Espino (usar tenant_scope / espino_scope).
FORBIDDEN = (
    re.compile(r"\bdemo\.GAP_ESPECIES\b"),
    re.compile(r"\bdemo\.LIBRO_CAMPO_ESPECIES\b"),
    re.compile(r"\bdemo\.CENTROS_COSTO\b"),
    re.compile(r"\bdemo\.CUARTELES_OFICIALES\b"),
)

ALLOWED_EXCEPTIONS: dict[str, set[int]] = {
    # Ninguna por ahora — si hace falta una línea legacy, documentar aquí con número de línea.
}


def main() -> int:
    errors: list[str] = []
    for pattern in GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if i in ALLOWED_EXCEPTIONS.get(str(rel), set()):
                    continue
                for rx in FORBIDDEN:
                    if rx.search(line):
                        errors.append(f"{rel}:{i}: {line.strip()}")
    if errors:
        print("Espino tenant purity check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nUse demo_web.services.tenant_scope (centros_costo, libro_campo_especies, …).",
            file=sys.stderr,
        )
        return 1
    print("Espino tenant purity check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
