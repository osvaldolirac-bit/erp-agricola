#!/usr/bin/env python3
"""Parche costos.py: matriz Espino incluye CEREZOS y redistribuye a variedades.

Uso: python3 scripts/patch_costos_espino_cerezos.py [/root/demo-web/demo_web/services/native/costos.py]
"""
from __future__ import annotations

import sys
from pathlib import Path

IMPORT_ANCHOR = "from demo_web.services.lc_excluir_espino import ("
IMPORT_ADD = """from demo_web.services.espino_costos import (
    cuarteles_matriz_espino,
    cuarteles_vista_espino,
    preparar_matriz_costos_espino,
)
from demo_web.services.tenant_scope import is_espino_tenant
"""

OLD = """    cuarteles_full = cuarteles_oficiales(demo)
    cuarteles = cuarteles_costos_lc(cuarteles_full)"""

NEW = """    if is_espino_tenant():
        cuarteles_full = cuarteles_matriz_espino(demo)
        cuarteles = cuarteles_vista_espino(demo)
    else:
        cuarteles_full = cuarteles_oficiales(demo)
        cuarteles = cuarteles_costos_lc(cuarteles_full)"""

OLD2 = """        matriz, det_fi, det_ff = _armar_matriz_costos_tenant(
            demo, conn, es_vigente=es_vigente, fi=fi, ff=ff,
            cuarteles_full=cuarteles_full, prorr=prorr, nombre=nombre,
        )
        matriz_bruta = None"""

NEW2 = """        matriz, det_fi, det_ff = _armar_matriz_costos_tenant(
            demo, conn, es_vigente=es_vigente, fi=fi, ff=ff,
            cuarteles_full=cuarteles_full, prorr=prorr, nombre=nombre,
        )
        if is_espino_tenant():
            matriz = preparar_matriz_costos_espino(demo, conn, matriz)
        matriz_bruta = None"""

OLD3 = """            matriz_bruta = _armar_matriz_costos_bruta(
                demo, conn, es_vigente=es_vigente, fi=fi, ff=ff,
                cuarteles_full=cuarteles_full, prorr=prorr, nombre=nombre,
            )

        if es_vigente:"""

NEW3 = """            matriz_bruta = _armar_matriz_costos_bruta(
                demo, conn, es_vigente=es_vigente, fi=fi, ff=ff,
                cuarteles_full=cuarteles_full, prorr=prorr, nombre=nombre,
            )
            if is_espino_tenant():
                matriz_bruta = preparar_matriz_costos_espino(demo, conn, matriz_bruta)

        if es_vigente:"""


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/demo-web/demo_web/services/native/costos.py")
    text = path.read_text(encoding="utf-8")
    if "preparar_matriz_costos_espino" in text:
        print("OK — ya parcheado")
        return
    if IMPORT_ADD.strip() not in text:
        if IMPORT_ANCHOR not in text:
            raise SystemExit("Ancla import no encontrada")
        text = text.replace(IMPORT_ANCHOR, IMPORT_ADD + IMPORT_ANCHOR, 1)
    for old, new, label in ((OLD, NEW, "cuarteles"), (OLD2, NEW2, "matriz"), (OLD3, NEW3, "matriz_bruta")):
        if old not in text:
            raise SystemExit(f"Bloque {label} no encontrado")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print(f"OK — costos Espino CEREZOS redistrib en {path}")


if __name__ == "__main__":
    main()
