#!/usr/bin/env python3
"""Parche app_demo: menú certificación/consultor GlobalGAP."""
from __future__ import annotations

from pathlib import Path

MENU = """MENU_GLOBALGAP = [
    ("🌿 PANEL CONSULTOR", "PanelGlobalGAP"),
    ("🌿 GLOBALGAP", "GlobalGAP"),
    ("🆘 SOPORTE", "Soporte"),
    ("📖 MANUAL", "Manual"),
]"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "MENU_GLOBALGAP" in text:
        print(f"skip {path}: already has MENU_GLOBALGAP")
        return False
    anchor = "MENU_CERTIFICACION = ["
    idx = text.find(anchor)
    if idx < 0:
        print(f"skip {path}: no MENU_CERTIFICACION")
        return False
    insert_at = text.rfind("\n", 0, idx)
    new_text = text[: insert_at + 1] + MENU + "\n\n" + text[insert_at + 1 :]
    path.write_text(new_text, encoding="utf-8")
    print(f"patched {path}")
    return True


def main() -> None:
    root = Path("/root/demo-web")
    for name in ("app_demo.py",):
        p = root / name
        if p.is_file():
            patch(p)


if __name__ == "__main__":
    main()
