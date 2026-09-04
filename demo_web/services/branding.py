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
    for raw in (
        os.environ.get("ERP_LOGO_DIR"),
        "/root/static",
        str(Path(__file__).resolve().parents[3] / "static"),
        str(Path(__file__).resolve().parents[1] / "static" / "img"),
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
    """Logo ERP Master (marca plataforma)."""
    return _first_existing(_MASTER_LOGO_NAMES)


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
