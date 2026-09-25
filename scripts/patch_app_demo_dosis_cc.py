#!/usr/bin/env python3
"""Parche app_demo.py: dosis cc sin decimales confusos en PDF Libro de Campo."""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path("/root/demo-web/app_demo.py")

FN = '''

def f_dosis_lc_unidad(v, unidad_dosis=""):
    """Dosis /100L: cc enteros (80 cc) sin 80,000 confuso."""
    u = (unidad_dosis or "").lower()
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "0" if ("cc" in u or "cúbico" in u or "cubico" in u) else "0,000"
    if "cc" in u or "cúbico" in u or "cubico" in u:
        if abs(x - round(x)) < 1e-9:
            return str(int(round(x)))
        s = f"{x:.2f}".replace(".", ",")
        return s.rstrip("0").rstrip(",") or "0"
    return f_dosis_lc(x)

'''

OLD = '                    if col == "DOSIS 100L":\n                        val = f_dosis_lc(val)'
NEW = '                    if col == "DOSIS 100L":\n                        val = f_dosis_lc_unidad(val, row.get("UNIDAD", ""))'


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else APP
    if not path.is_file():
        print(f"ERROR: no existe {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    if "def f_dosis_lc_unidad" not in text:
        marker = "def f_dosis_lc(v):"
        idx = text.find(marker)
        if idx < 0:
            print("ERROR: no se encontró f_dosis_lc", file=sys.stderr)
            return 1
        end = text.find("\n\n", idx)
        if end < 0:
            end = text.find("\ndef ", idx + 1)
        text = text[: end + 1] + FN + text[end + 1 :]
        print("OK — añadida f_dosis_lc_unidad")
    if OLD not in text:
        if NEW.split("\n")[1].strip() in text:
            print("OK — generar_pdf_libro_campo ya parcheado")
        else:
            print("WARN: bloque generar_pdf_libro_campo no encontrado", file=sys.stderr)
    else:
        text = text.replace(OLD, NEW, 1)
        print("OK — generar_pdf_libro_campo parcheado")
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
