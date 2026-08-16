"""Bitácora operativa Constructora — respeta flag erp_status/<slug>.bitacora."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

_STATUS_DIR = os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"
_DEFAULT_SLUG = (
    os.environ.get("CONSTRUCTORA_TENANT_SLUG", "constructora-demo").strip()
    or "constructora-demo"
)


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", (slug or _DEFAULT_SLUG).lower())


def hora_chile() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:
        return datetime.now(timezone.utc) - timedelta(hours=4)


def bitacora_erp_activa(slug: str | None = None) -> bool:
    safe = _safe_slug(slug or _DEFAULT_SLUG)
    path = os.path.join(_STATUS_DIR, f"{safe}.bitacora")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def ensure_bitacora_schema(c) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS bitacora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT,
            accion TEXT,
            detalle TEXT,
            fecha_hora TEXT
        )
        """
    )


def registrar_bitacora(
    c,
    usuario: str,
    accion: str,
    detalle: str = "",
    *,
    slug: str | None = None,
) -> None:
    if not bitacora_erp_activa(slug):
        return
    ensure_bitacora_schema(c)
    f_h = hora_chile().strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute(
            "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
            (
                (usuario or "SISTEMA").strip() or "SISTEMA",
                (accion or "ACCION").strip() or "ACCION",
                (detalle or "")[:500],
                f_h,
            ),
        )
    except Exception:
        pass
