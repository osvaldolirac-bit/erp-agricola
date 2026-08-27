#!/usr/bin/env python3
"""Corrige rutas Registros * en catálogo espino y BD gap_documentos."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DOCS = Path("/root/demo-web/demo_web/static/globalgap/docs")
DB = Path("/root/erp_concepcion_v6.db")
CATALOG = DOCS / "catalogo_espino.json"
ESPECIE = "EL ESPINO"
FROM_PREFIX = "Registros La Concepcion/"
TO_PREFIX = "Registros El Espino/"


def fix_catalog() -> int:
    if not CATALOG.is_file():
        print(f"SKIP catálogo: no existe {CATALOG}")
        return 0
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    n = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("archivo_relpath") or "")
        if rel.startswith(FROM_PREFIX):
            item["archivo_relpath"] = TO_PREFIX + rel[len(FROM_PREFIX) :]
            item["especie"] = ESPECIE
            n += 1
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK catálogo: {n} rutas actualizadas")
    return n


def fix_db() -> int:
    if not DB.is_file():
        raise SystemExit(f"No existe {DB}")
    conn = sqlite3.connect(DB)
    try:
        n = conn.execute(
            """UPDATE gap_documentos
               SET archivo_relpath = ? || SUBSTR(archivo_relpath, ?)
               WHERE COALESCE(especie,'')=? AND archivo_relpath LIKE ?""",
            (TO_PREFIX, len(FROM_PREFIX) + 1, ESPECIE, FROM_PREFIX + "%"),
        ).rowcount
        conn.commit()
        print(f"OK BD gap_documentos: {n} rutas actualizadas")
        return n
    finally:
        conn.close()


def main() -> int:
    fix_catalog()
    fix_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
