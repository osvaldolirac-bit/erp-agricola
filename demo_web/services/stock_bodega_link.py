"""Link móvil stock + kardex LC (token en URL, sin /login — patrón registro-riego)."""
from __future__ import annotations

import os
import secrets
import sqlite3

from flask import current_app

from demo_web.services.demo_loader import get_demo_module, get_erp_app

_META_KEY = "stock_bodega_link_token_v1"


def _conn() -> sqlite3.Connection:
    demo = get_demo_module()
    return demo.conectar_db()


def migrar_tabla(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = _conn()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
        )
        row = conn.execute(
            "SELECT valor FROM schema_meta WHERE clave=?", (_META_KEY,)
        ).fetchone()
        if not row:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT INTO schema_meta (clave, valor) VALUES (?, ?)",
                (_META_KEY, token),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def _token_db(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave=?", (_META_KEY,)
    ).fetchone()
    return str(row[0]).strip() if row and row[0] else None


def obtener_token() -> str:
    conn = _conn()
    try:
        migrar_tabla(conn)
        token = _token_db(conn)
        if not token:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, ?)",
                (_META_KEY, token),
            )
            conn.commit()
        return token
    finally:
        conn.close()


def token_valido(recibido: str | None) -> bool:
    if not recibido or not recibido.strip():
        return False
    conn = _conn()
    try:
        migrar_tabla(conn)
        esperado = _token_db(conn)
        if not esperado:
            return False
        return secrets.compare_digest(recibido.strip(), esperado)
    finally:
        conn.close()


def url_publica(token: str | None = None) -> str:
    tok = token or obtener_token()
    base = (
        os.environ.get("ERP_PUBLIC_BASE_URL")
        or current_app.config.get("ERP_PUBLIC_BASE_URL")
        or "https://erpmaster.cl"
    ).rstrip("/")
    prefix = (current_app.config.get("APPLICATION_ROOT") or "/agricola").rstrip("/")
    return f"{base}{prefix}/stock-bodega?t={tok}"


def habilitado() -> bool:
    return get_erp_app() == "concepcion"
