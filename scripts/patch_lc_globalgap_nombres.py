#!/usr/bin/env python3
"""Renombra etiquetas GlobalGAP La Concepción: Cerezos→LA CONCEPCION, etc."""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

APP = Path("/root/demo-web/app_concepcion.py")
DB = Path("/root/erp_concepcion_v6.db")

RENAMES = (
    ("Cerezos", "LA CONCEPCION"),
    ("Ciruelos", "CARLOS LIRA"),
    ("Nogales", "EL ESPINO"),
)

TABLES_WITH_ESPECIE = (
    "gantt_proyectos",
    "gap_cosecha",
    "gap_doc_checklist",
    "gap_documentos",
    "gap_evaluacion",
    "gap_nc",
    "gap_orden_aplicacion",
    "gap_pppl",
    "libro_campo",
)


def patch_app() -> None:
    if not APP.is_file():
        raise SystemExit(f"No existe {APP}")
    text = APP.read_text(encoding="utf-8")
    old_block = '''GAP_ESPECIES = ["Cerezos", "Ciruelos", "Nogales"]
GAP_ESPECIE_CUARTELES = {
    "Cerezos": ["CEREZOS CORTE 1", "CEREZOS CORTE 2"],
    "Ciruelos": ["CIRUELOS"],
    "Nogales": ["NOGALES APARICION", "NOGALES CRUZ DEL SUR"],
}'''
    new_block = '''GAP_ESPECIES = ["LA CONCEPCION", "CARLOS LIRA", "EL ESPINO"]
GAP_ESPECIE_CUARTELES = {
    "LA CONCEPCION": ["CEREZOS CORTE 1", "CEREZOS CORTE 2"],
    "CARLOS LIRA": ["CIRUELOS"],
    "EL ESPINO": ["NOGALES APARICION", "NOGALES CRUZ DEL SUR"],
}'''
    if new_block in text:
        print("app_concepcion.py ya parcheado")
        return
    if old_block not in text:
        raise SystemExit("Bloque GAP_ESPECIES no encontrado (¿ya modificado?)")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = APP.with_suffix(f".py.bak_gap_nombres_{ts}")
    shutil.copy2(APP, bak)
    APP.write_text(text.replace(old_block, new_block, 1), encoding="utf-8")
    print(f"OK app_concepcion.py (backup {bak.name})")


def migrate_db() -> None:
    if not DB.is_file():
        raise SystemExit(f"No existe {DB}")
    conn = sqlite3.connect(DB)
    try:
        for old, new in RENAMES:
            for tbl in TABLES_WITH_ESPECIE:
                try:
                    n = conn.execute(
                        f"UPDATE {tbl} SET especie=? WHERE especie=?",
                        (new, old),
                    ).rowcount
                    if n:
                        print(f"  {tbl}: {old} → {new} ({n} filas)")
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
        conn.commit()
    finally:
        conn.close()
    print("OK migración BD")


def main() -> int:
    patch_app()
    migrate_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
