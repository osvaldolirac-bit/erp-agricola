#!/usr/bin/env python3
"""Restaura tenant_admin desde backup VPS y fusiona prorrateo Espino."""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKUP = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/backups/erp_master/20260826_231927/code/erp_master/tenant_admin.py"
)
TARGET = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else "/root/erp_master/erp_master/tenant_admin.py"
)

ESPINO_BLOCK = '''    "espino": {
        "cuarteles": [
            "ROYAL DOWN",
            "SWEET ARYANA",
            "SANTINA",
        ],
        "default_pct": {
            "ROYAL DOWN": 33.33,
            "SWEET ARYANA": 33.33,
            "SANTINA": 33.34,
        },
        "default_ha": {},
        "directos": ["EL ESPINO"],
    },
'''

LC_FAMILY_HELPER = '''def _is_lc_family(kind: str) -> bool:
    """La Concepción y El Espino comparten roles/módulos LC."""
    return kind in ("lc", "espino")


'''


def main() -> None:
    if not BACKUP.is_file():
        raise SystemExit(f"Backup no encontrado: {BACKUP}")
    text = BACKUP.read_text(encoding="utf-8")

    if "_is_lc_family" not in text:
        anchor = "_EMAIL_RE = re.compile"
        if anchor not in text:
            raise SystemExit("No se encontró ancla _EMAIL_RE")
        text = text.replace(anchor, LC_FAMILY_HELPER + anchor, 1)
        text = re.sub(r'\bif kind == "lc":', "if _is_lc_family(kind):", text)
        text = text.replace(
            "mail_petroleo if kind == \"lc\" else None",
            "mail_petroleo if _is_lc_family(kind) else None",
        )
        text = text.replace(
            "solo_lectura if kind == \"lc\" else None",
            "solo_lectura if _is_lc_family(kind) else None",
        )

    if '"espino": {' not in text:
        needle = '        "directos": ["EL ESPINO", "OTROS"],\n    },\n}'
        if needle not in text:
            raise SystemExit("No se encontró bloque _PRORRATEO_DEFAULTS lc")
        text = text.replace(needle, '        "directos": ["EL ESPINO", "OTROS"],\n    },\n' + ESPINO_BLOCK + "}", 1)

    TARGET.write_text(text, encoding="utf-8")
    print(f"OK — {TARGET} ({len(text.splitlines())} líneas)")


if __name__ == "__main__":
    main()
