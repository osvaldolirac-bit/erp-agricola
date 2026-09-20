#!/usr/bin/env python3
"""Normaliza GGRG02 (Orden Aplicación Fitosanitarios) para El Espino — formato digital sin archivo."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DOCS = Path("/root/demo-web/demo_web/static/globalgap/docs")
DB = Path("/root/erp_concepcion_v6.db")
CATALOG = DOCS / "catalogo_espino.json"
NOTAS = (
    "Formato digital: la orden se registra en Libro de Campo / PPPL. "
    "No hay plantilla física en el repositorio GlobalGAP."
)


def fix_catalog() -> bool:
    if not CATALOG.is_file():
        print(f"SKIP catálogo: no existe {CATALOG}")
        return False
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    changed = False
    for item in data:
        if not isinstance(item, dict) or item.get("codigo") != "GGRG02":
            continue
        if item.get("especie") != "EL ESPINO":
            item["especie"] = "EL ESPINO"
            changed = True
        if not str(item.get("formato") or "").strip():
            item["formato"] = "Digital"
            changed = True
        if str(item.get("archivo_relpath") or "").strip():
            item["archivo_relpath"] = ""
            item["nombre_archivo"] = ""
            changed = True
    if changed:
        CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK catálogo GGRG02 changed={changed}")
    return changed


def fix_db() -> int:
    if not DB.is_file():
        raise SystemExit(f"No existe {DB}")
    conn = sqlite3.connect(DB)
    try:
        n = conn.execute(
            """UPDATE gap_documentos SET
                 titulo=COALESCE(NULLIF(TRIM(titulo), ''), 'Orden Aplicación Fitosanitarios'),
                 formato='Digital',
                 archivo_relpath='',
                 nombre_archivo='',
                 notas=?
               WHERE codigo='GGRG02' AND COALESCE(especie,'')='EL ESPINO'""",
            (NOTAS,),
        ).rowcount
        conn.commit()
        print(f"OK BD gap_documentos GGRG02: {n} fila(s)")
        return n
    finally:
        conn.close()


def main() -> int:
    fix_catalog()
    fix_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
