#!/usr/bin/env python3
"""Parche compras agro: ingreso kardex bodega al comprar (tenant Espino).

Uso: python3 scripts/patch_compras_kardex_espino.py [/root/demo-web/demo_web/services/native/compras.py]
"""
from __future__ import annotations

import sys
from pathlib import Path

HELPER = '''

def _espino_kardex_ingreso_compra(conn, demo, producto_id: int, cantidad: float, fecha: str, pmp: float, um: str) -> None:
    """Registra ingreso kardex bodega El Espino al recibir compra agro."""
    try:
        from flask import g
        slug = str(getattr(g, "tenant_slug", None) or "").strip().lower()
    except Exception:
        slug = ""
    if slug != "espino" or cantidad <= 0:
        return
    cc = "Cerezos"
    conn.execute(
        """INSERT INTO movimientos
           (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
           VALUES (?,?,?,?,?,?,?)""",
        (int(producto_id), "Ingreso", float(cantidad), fecha, cc, float(cantidad) * float(pmp or 0), um),
    )
'''

INSERT_AFTER_NEW = """            new_id = cur_ins.lastrowid
            if not nia:"""

INSERT_AFTER_NEW_REPL = """            new_id = cur_ins.lastrowid
            _espino_kardex_ingreso_compra(
                conn, demo, new_id, float(i["c"]), fe, float(i["p"]), i.get("um", demo.DEFAULT_UNIDAD_INSUMO)
            )
            if not nia:"""

INSERT_AFTER_UPDATE = """            conn.execute(
                "UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?",
                (i["c"], npmp, i["id"]),
            )"""

INSERT_AFTER_UPDATE_REPL = """            conn.execute(
                "UPDATE inventario SET stock = stock + ?, precio_medio = ? WHERE id = ?",
                (i["c"], npmp, i["id"]),
            )
            _espino_kardex_ingreso_compra(
                conn, demo, int(i["id"]), float(i["c"]), fe, float(npmp), i.get("um", demo.DEFAULT_UNIDAD_INSUMO)
            )"""


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/demo-web/demo_web/services/native/compras.py")
    text = path.read_text(encoding="utf-8")
    if "_espino_kardex_ingreso_compra" in text:
        print("OK — ya parcheado")
        return
    anchor = "def _post_save_agro(demo, conn) -> dict:"
    if anchor not in text:
        raise SystemExit(f"No se encontró {anchor} en {path}")
    text = text.replace(anchor, HELPER + anchor, 1)
    if INSERT_AFTER_NEW not in text:
        raise SystemExit("Bloque new_id no encontrado")
    text = text.replace(INSERT_AFTER_NEW, INSERT_AFTER_NEW_REPL, 1)
    if INSERT_AFTER_UPDATE not in text:
        raise SystemExit("Bloque UPDATE stock no encontrado")
    text = text.replace(INSERT_AFTER_UPDATE, INSERT_AFTER_UPDATE_REPL, 1)
    path.write_text(text, encoding="utf-8")
    print(f"OK — kardex compras Espino en {path}")


if __name__ == "__main__":
    main()
