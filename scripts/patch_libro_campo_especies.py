#!/usr/bin/env python3
"""Separa especies de Libro de Campo de GAP_ESPECIES (ámbitos GlobalGAP / razones sociales).

Uso en VPS:
  python3 scripts/patch_libro_campo_especies.py /root/demo-web/app_concepcion.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "LIBRO_CAMPO_ESPECIES"
INSERT = 'LIBRO_CAMPO_ESPECIES = ["Cerezos", "Ciruelos", "Nogales"]\n'


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"OK (ya parcheado): {path}")
        return True
    needle = "GAP_ESPECIE_GENERAL = "
    idx = text.find(needle)
    if idx == -1:
        print(f"ERROR: no se encontró {needle!r} en {path}", file=sys.stderr)
        return False
    updated = text[:idx] + INSERT + text[idx:]
    path.write_text(updated, encoding="utf-8")
    print(f"Parcheado: {path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="app_concepcion.py (y opcionalmente app_demo.py)",
    )
    ok = all(patch(p) for p in parser.parse_args().files)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
