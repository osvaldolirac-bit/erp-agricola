#!/usr/bin/env python3
"""Agrega tenant El Espino a /root/scripts/erp_respaldo_cron.py si falta."""
from __future__ import annotations

import sys
from pathlib import Path

CRON = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/scripts/erp_respaldo_cron.py")

ENTRY = """    {
        "nombre": "ERP Agrícola El Espino",
        "db": "/root/espino/erp_espino.db",
        "secrets": "/root/espino/.streamlit/secrets.toml",
        "producto": "agricola",
    },
"""

MARKER = '"nombre": "ERP Agrícola El Espino"'
INSERT_AFTER = '"producto": "agricola",\n    },\n    {\n        "nombre": "ERP DEMO AGRICOLA",'


def main() -> int:
    if not CRON.is_file():
        print(f"ERROR: missing {CRON}", file=sys.stderr)
        return 1
    text = CRON.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"OK already present: {CRON}")
        return 0
    needle = INSERT_AFTER
    if needle not in text:
        print("ERROR: anchor not found for insert", file=sys.stderr)
        return 1
    patched = text.replace(
        needle,
        '"producto": "agricola",\n    },\n' + ENTRY + "    {\n        \"nombre\": \"ERP DEMO AGRICOLA\",",
        1,
    )
    CRON.write_text(patched, encoding="utf-8")
    print(f"Patched Espino entry in {CRON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
