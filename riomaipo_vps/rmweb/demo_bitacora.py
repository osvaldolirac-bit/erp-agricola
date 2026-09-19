"""Movimientos DEMO Comercial → Super Consola (+ ERP si flag activa)."""
from __future__ import annotations

from rmweb.master_bitacora import log_master_bitacora

DEMO_SLUG = "comercial-demo"


def _session_user() -> str:
    try:
        from flask import session

        return (
            (session.get("auth_user") or session.get("email") or "sistema").strip()
            or "sistema"
        )
    except Exception:
        return "sistema"


def _session_slug() -> str:
    try:
        from flask import session

        return (session.get("tenant_slug") or "").strip().lower()
    except Exception:
        return ""


def log_movimiento_demo(accion: str, detalle: str = "", *, usuario: str | None = None) -> None:
    slug = _session_slug()
    if slug != DEMO_SLUG:
        return
    user = (usuario or _session_user()).strip() or "sistema"
    log_master_bitacora(slug, user, accion, detalle)
