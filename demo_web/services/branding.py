"""Logo y assets de marca (rubro agrícola / ERP Master)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_MASTER_LOGO_NAMES = (
    "logo_erpmaster.png",
    "logo_erpmaster.jpg",
    "logo_erpmaster.svg",
    "logo_erpmaster_email.png",
)

_LEGACY_LOGO_NAMES = (
    "logo_concepcion.png",
    "logo_concepcion.jpg",
    "logo_concepcion.jpeg",
    "logo_concepcion.svg",
)

_ESPINO_LOGO_NAMES = (
    "logo_espino.png",
    "logo_espino.jpg",
    "logo_espino.jpeg",
    "logo_espino.svg",
)


def _logo_dirs() -> list[Path]:
    dirs: list[Path] = []
    bundled = Path(__file__).resolve().parents[1] / "static" / "img"
    if bundled.is_dir():
        dirs.append(bundled)
    for raw in (
        os.environ.get("ERP_LOGO_DIR"),
        "/root/static",
        str(Path(__file__).resolve().parents[3] / "static"),
    ):
        if raw:
            p = Path(raw)
            if p.is_dir() and p not in dirs:
                dirs.append(p)
    return dirs


def _first_existing(names: tuple[str, ...]) -> Path | None:
    for d in _logo_dirs():
        for name in names:
            p = d / name
            if p.is_file():
                return p
    return None


def find_logo_path(prefer_master: bool = True) -> Path | None:
    if prefer_master:
        found = _first_existing(_MASTER_LOGO_NAMES)
        if found:
            return found
        # sin logo master, no caer al de LC en la pantalla del rubro
        return None
    return _first_existing(_LEGACY_LOGO_NAMES)


def find_master_logo_path() -> Path | None:
    """Logo ERP Master (marca plataforma). Prioriza PNG embebido en repo."""
    return _first_existing(_MASTER_LOGO_NAMES)


def master_logo_data_uri() -> str | None:
    """Data-URI del logo (sin depender de /static ni /assets en nginx)."""
    import base64
    import mimetypes

    path = find_master_logo_path()
    if not path:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def tenant_shows_master_brand(slug: str | None, tenant: dict | None = None) -> bool:
    """Watermark ERP Master fijo (LC + El Espino)."""
    from demo_web.services.tenant_rules import muestra_logo_erpmaster

    key = (slug or (tenant or {}).get("slug") or "").strip().lower()
    if muestra_logo_erpmaster(key):
        return True
    kind = ((tenant or {}).get("kind") or "").strip().lower()
    return kind == "lc"


_TENANT_LOGO_NAMES: dict[str, tuple[str, ...]] = {
    "concepcion": _LEGACY_LOGO_NAMES,
    "espino": _ESPINO_LOGO_NAMES,
}


def find_tenant_logo_path(slug: str | None) -> Path | None:
    """Logo del cliente según tenant (p. ej. La Concepción)."""
    key = (slug or "").strip().lower()
    names = _TENANT_LOGO_NAMES.get(key)
    if not names:
        return None
    return _first_existing(names)


def resolve_tenant_slug(demo: Any = None) -> str:
    """Slug activo: sesión Flask, módulo ERP cargado o ruta de la DB."""
    try:
        from flask import g, has_request_context, session

        if has_request_context():
            slug = getattr(g, "tenant_slug", None) or session.get("tenant_slug")
            if slug:
                return str(slug).strip().lower()
    except Exception:
        pass

    mod = demo
    if mod is None:
        try:
            from demo_web.services.demo_loader import get_demo_module

            mod = get_demo_module()
        except Exception:
            mod = None

    if mod is not None:
        slug = (getattr(mod, "TENANT_SLUG", None) or "").strip().lower()
        if slug:
            return slug
        db = (getattr(mod, "NOMBRE_DB", None) or "").lower()
        if "espino" in db:
            return "espino"
        if "concepcion" in db:
            return "concepcion"

    slug = (os.environ.get("ERP_TENANT_SLUG") or os.environ.get("ERP_TENANT") or "").strip().lower()
    if slug:
        return slug
    db = (os.environ.get("ERP_DB") or os.environ.get("ERP_ESPINO_DB") or "").lower()
    if "espino" in db:
        return "espino"
    return ""


def logo_path_for_pdf(demo: Any = None) -> str | None:
    """Ruta de logo para PDFs. El Espino nunca usa el logo de La Concepción."""
    slug = resolve_tenant_slug(demo)
    if slug:
        found = find_tenant_logo_path(slug)
        if found:
            return str(found)
        if slug == "espino":
            return None
    if slug == "espino":
        return None
    found = find_tenant_logo_path("concepcion")
    if found:
        return str(found)
    return None


def tenant_logo_path_or_none(slug: str | None) -> Path | None:
    """Logo del tenant; None si Espino sin archivo (evita cruzar marcas)."""
    key = (slug or "").strip().lower()
    if key == "espino":
        return find_tenant_logo_path("espino")
    if key:
        return find_tenant_logo_path(key)
    return None


_ESPINO_BRAND_RGB = (60, 91, 62)
_ESPINO_BRAND_HEX = "#3c5b3e"


def _pdf_txt(texto: str) -> str:
    return str(texto or "").encode("latin-1", "replace").decode("latin-1")


def _espino_pdf_logo_padded(src: Path, *, ratio: float = 0.16) -> Path:
    """Logo Espino con margen blanco para PDFs (más aire alrededor del emblema)."""
    out = src.parent / "logo_espino_pdf_pad.png"
    try:
        if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
    except OSError:
        pass
    try:
        from PIL import Image
    except ImportError:
        return src
    try:
        im = Image.open(src).convert("RGBA")
        pad = max(24, int(min(im.size) * ratio))
        canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (255, 255, 255, 255))
        canvas.paste(im, (pad, pad), im if im.mode == "RGBA" else None)
        canvas.save(out, format="PNG", optimize=True)
        return out
    except OSError:
        return src


def pdf_logo_path_for_draw(demo: Any = None) -> str | None:
    """Ruta de logo lista para PDF (Espino incluye padding)."""
    raw = logo_path_for_pdf(demo)
    if not raw:
        return None
    slug = resolve_tenant_slug(demo)
    if slug == "espino":
        return str(_espino_pdf_logo_padded(Path(raw)))
    return raw


def pdf_draw_tenant_logo(pdf, logo_path: str | None = None, demo: Any = None) -> tuple[bool, float | None]:
    """Dibuja logo tenant en membrete PDF.

    Retorna (dibujado, y_titulo). y_titulo sugerido solo para Espino (logo + EL ESPINO).
    """
    slug = resolve_tenant_slug(demo)
    path = logo_path or pdf_logo_path_for_draw(demo)
    if not path:
        return False, None
    if slug == "espino":
        path = str(_espino_pdf_logo_padded(Path(path)))
    try:
        if slug == "espino":
            logo_x, logo_y, logo_h = 14, 11, 20
            pdf.image(path, x=logo_x, y=logo_y, h=logo_h)
            pdf.set_font("Helvetica", "B", 17)
            pdf.set_text_color(*_ESPINO_BRAND_RGB)
            pdf.set_xy(logo_x, logo_y + logo_h + 1.2)
            pdf.cell(logo_h, 6.5, _pdf_txt("EL ESPINO"), align="C")
            pdf.set_text_color(0, 0, 0)
            return True, logo_y + logo_h + 9.5
        pdf.image(path, x=10, y=8, w=40)
        return True, None
    except Exception:
        return False, None
