#!/usr/bin/env python3
"""Genera /root/static/logo_espino.png si no existe (PDFs tenant El Espino)."""
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    out_dir = Path(os.environ.get("ERP_LOGO_DIR", "/root/static"))
    out = out_dir / "logo_espino.png"
    if out.is_file():
        print(f"OK — ya existe {out}")
        return 0
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        print(f"ERROR: Pillow requerido: {exc}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = 420, 120
    img = Image.new("RGB", (w, h), "#558B2F")
    draw = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = font_big

    draw.text((w // 2, 42), "EL ESPINO", fill="white", font=font_big, anchor="mm")
    draw.text((w // 2, 82), "ERP Agrícola", fill="#E8F5E9", font=font_small, anchor="mm")
    img.save(out, format="PNG", optimize=True)
    print(f"OK — creado {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
