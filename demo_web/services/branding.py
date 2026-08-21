"""Logo y assets de marca (rubro agrícola / ERP Master)."""
from __future__ import annotations

import os
from pathlib import Path

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
}


def find_tenant_logo_path(slug: str | None) -> Path | None:
    """Logo del cliente según tenant (p. ej. La Concepción)."""
    key = (slug or "").strip().lower()
    names = _TENANT_LOGO_NAMES.get(key)
    if not names:
        return None
    return _first_existing(names)
