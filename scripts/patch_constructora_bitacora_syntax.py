#!/usr/bin/env python3
"""Corrige SyntaxError en constructora/rmweb/bitacora.py (try sin except)."""
from __future__ import annotations

from pathlib import Path

PATH = Path("/root/constructora/rmweb/bitacora.py")

OLD = """        )
    try:
        from rmweb.master_bitacora import log_master_bitacora"""

NEW = """        )
    except Exception:
        pass
    try:
        from rmweb.master_bitacora import log_master_bitacora"""


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if NEW in text:
        print("already patched")
        return
    if OLD not in text:
        raise SystemExit("anchor not found")
    PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("bitacora.py: ok")


if __name__ == "__main__":
    main()
