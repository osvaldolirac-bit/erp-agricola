#!/usr/bin/env python3
"""Evita salida bodega LC duplicada: tenant Espino usa espino_bodega/LC.

Uso: python3 scripts/patch_bodega_block_espino_salida.py [compras.py path -> bodega.py path]
"""
from __future__ import annotations

import sys
from pathlib import Path

GUARD = '''    try:
        from flask import g
        if str(getattr(g, "tenant_slug", None) or "").strip().lower() == "espino":
            return {
                "ok": False,
                "msg": "En El Espino las salidas van por Libro de Campo (rebaje automático). No use Salida bodega aquí.",
            }
    except Exception:
        pass

'''


def main() -> None:
    path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "/root/demo-web/demo_web/services/native/bodega.py"
    )
    text = path.read_text(encoding="utf-8")
    if "En El Espino las salidas van por Libro de Campo" in text:
        print("OK — ya parcheado")
        return
    anchor = "def _procesar_salida(demo, conn) -> dict:"
    if anchor not in text:
        raise SystemExit(f"No se encontró {anchor}")
    # insert after docstring-less function start, after first line try iid
    insert_at = "def _procesar_salida(demo, conn) -> dict:\n    try:"
    if insert_at not in text:
        raise SystemExit("Estructura _procesar_salida inesperada")
    text = text.replace(insert_at, "def _procesar_salida(demo, conn) -> dict:\n" + GUARD + "    try:", 1)
    path.write_text(text, encoding="utf-8")
    print(f"OK — guard Espino salida en {path}")


if __name__ == "__main__":
    main()
