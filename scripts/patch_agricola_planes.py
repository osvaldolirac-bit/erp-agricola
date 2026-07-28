#!/usr/bin/env python3
"""Aplica Planes DEMO Agrícola (Pack Campo/Patio/Oficina/Agrícola + eje Costos)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "demo_web"
DST = Path("/root/demo-web/demo_web")


def main() -> None:
    if not DST.exists():
        raise SystemExit(f"Destino no existe: {DST}")
    shutil.copy2(SRC / "pricing.py", DST / "pricing.py")
    shutil.copy2(SRC / "templates" / "planes.html", DST / "templates" / "planes.html")
    shutil.copy2(SRC / "app.py", DST / "app.py")
    css_frag = (SRC / "static" / "css" / "planes.css").read_text(encoding="utf-8")
    erp = DST / "static" / "css" / "erp.css"
    text = erp.read_text(encoding="utf-8")
    marker = "/* ===== Planes DEMO Agrícola ===== */"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n\n"
    erp.write_text(text + f"\n\n{marker}\n" + css_frag, encoding="utf-8")
    print("OK: pricing, planes.html, app.py, erp.css actualizados")


if __name__ == "__main__":
    main()
