"""Registro en master_bitacora (Super Consola) desde ERP Agrícola."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

DEMO_SLUGS = frozenset({"demo"})


def _hora_chile() -> str:
    try:
        return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_master_bitacora(
    tenant_slug: str,
    usuario: str,
    accion: str,
    detalle: str = "",
) -> None:
    slug = (tenant_slug or "").strip().lower()
    if not slug:
        return
    db_path = (os.environ.get("ERP_MASTER_DB") or "/root/erp_master.db").strip()
    if not db_path or not os.path.isfile(db_path):
        return
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        conn.execute(
            """
            INSERT INTO master_bitacora (tenant_slug, usuario, accion, detalle, fecha_hora)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                slug,
                (usuario or "").strip() or "sistema",
                (accion or "").strip() or "ACCION",
                (detalle or "").strip()[:500],
                _hora_chile(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
