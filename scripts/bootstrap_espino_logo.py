#!/usr/bin/env python3
"""Instala logo tenant El Espino en /root/static (UI + PDFs).

Prioridad:
  1. demo_web/static/img/logo_espino.{png,jpg,jpeg,svg} (repo)
  2. Placeholder verde solo si no hay archivo y --allow-placeholder

Uso:
  python3 scripts/bootstrap_espino_logo.py
  python3 scripts/bootstrap_espino_logo.py --force   # reemplaza placeholder verde
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

_PLACEHOLDER_MAX_BYTES = 6000
_NAMES = ("logo_espino.png", "logo_espino.jpg", "logo_espino.jpeg", "logo_espino.svg")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _search_dirs() -> list[Path]:
    dirs: list[Path] = []
    for raw in (
        os.environ.get("APP_ROOT"),
        os.environ.get("DEMO_WEB_ROOT"),
        str(_repo_root()),
        str(_repo_root() / "demo-web"),
        "/root/demo-web",
    ):
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir() and p not in dirs:
            dirs.append(p)
    return dirs


def _bundled_source() -> Path | None:
    for root in _search_dirs():
        img_dir = root / "demo_web" / "static" / "img"
        for name in _NAMES:
            p = img_dir / name
            if p.is_file():
                return p
    return None


def _is_placeholder(path: Path) -> bool:
    try:
        if path.stat().st_size <= _PLACEHOLDER_MAX_BYTES:
            return True
        from PIL import Image

        with Image.open(path) as im:
            return im.size == (420, 120)
    except Exception:
        return path.stat().st_size <= _PLACEHOLDER_MAX_BYTES


def _write_placeholder(out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    out.parent.mkdir(parents=True, exist_ok=True)
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


def install_logo(*, force: bool = False, allow_placeholder: bool = False) -> Path:
    out_dir = Path(os.environ.get("ERP_LOGO_DIR", "/root/static"))
    out = out_dir / "logo_espino.png"
    src = _bundled_source()

    if src and src.suffix.lower() != ".png":
        out_dir.mkdir(parents=True, exist_ok=True)
        if out.is_file() and not force and not _is_placeholder(out):
            return out
        shutil.copy2(src, out.with_suffix(src.suffix))
        if src.suffix.lower() != ".png":
            # PDFs y rutas legacy esperan .png; conservar también el original
            return out.with_suffix(src.suffix)
        return out

    if src:
        out_dir.mkdir(parents=True, exist_ok=True)
        if out.is_file() and not force and not _is_placeholder(out):
            print(f"OK — ya existe logo real {out}")
            return out
        shutil.copy2(src, out)
        print(f"OK — instalado {out} desde {src}")
        return out

    if out.is_file() and not force:
        if _is_placeholder(out):
            if allow_placeholder:
                print(f"WARN — placeholder verde {out} (sin logo en repo)")
                return out
            raise SystemExit(
                f"ERROR: {out} es placeholder verde. Agregue demo_web/static/img/logo_espino.png "
                "y ejecute con --force"
            )
        print(f"OK — ya existe {out}")
        return out

    if not allow_placeholder:
        raise SystemExit(
            "ERROR: falta demo_web/static/img/logo_espino.png en el repo. "
            "Suba el logo del tenant y vuelva a ejecutar."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_placeholder(out)
    print(f"WARN — creado placeholder verde {out}")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Instala logo El Espino en ERP_LOGO_DIR")
    p.add_argument("--force", action="store_true", help="Reemplaza placeholder o logo existente")
    p.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="Genera placeholder verde si no hay logo en repo (solo dev)",
    )
    args = p.parse_args()
    try:
        install_logo(force=args.force, allow_placeholder=args.allow_placeholder)
    except SystemExit as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
