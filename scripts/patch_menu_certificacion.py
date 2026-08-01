#!/usr/bin/env python3
"""Asegura DASHBOARD en MENU_CERTIFICACION de app_concepcion / app_demo."""
from __future__ import annotations

import re
import sys
from pathlib import Path

BLOCK = """MENU_CERTIFICACION = [
    ("🏠 DASHBOARD", "DASHBOARD"),
    ("🌿 GLOBALGAP", "GlobalGAP"),
    ("📒 LIBRO DE CAMPO", "Libro de Campo"),
    ("🏠 BODEGA", "Bodega"),
    ("🎫 SOPORTE", "Soporte"),
    ("📖 MANUAL", "Manual"),
]"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r"MENU_CERTIFICACION\s*=\s*\[[\s\S]*?\]",
        BLOCK,
        text,
        count=1,
    )
    if n:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> int:
    roots = [Path("/root/demo-web"), Path("."), Path("/workspace")]
    changed = []
    for root in roots:
        for name in ("app_concepcion.py", "app_demo.py"):
            p = root / name
            if p.is_file() and patch(p):
                changed.append(str(p))
    print("patched:", changed or "(none)")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
