#!/usr/bin/env python3
"""Espino: validar solo variedades en reparto CC (sin Cerezos / EL ESPINO bodega).

Uso: python3 scripts/patch_espino_clasificar_cc.py [/root/demo-web/app_concepcion.py]
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = """        if is_espino_tenant():
            valid = {c.upper() for c in ESPINO_CCS}
            valid.add(ETIQUETA_BODEGA.upper())
            directos = [c for c in sel if c in valid]"""

NEW = """        if is_espino_tenant():
            valid = {c.upper() for c in ESPINO_CCS}
            directos = [c for c in sel if c in valid]"""


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/demo-web/app_concepcion.py")
    text = path.read_text(encoding="utf-8")
    if OLD not in text:
        if "valid = {c.upper() for c in ESPINO_CCS}" in text and "ETIQUETA_BODEGA.upper()" not in text.split("ESPINO_CCS")[1].split("directos")[0]:
            print("OK — ya parcheado")
            return
        raise SystemExit("Bloque _clasificar_cc_seleccionados Espino no encontrado")
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"OK — variedades-only CC en {path}")


if __name__ == "__main__":
    main()
