from __future__ import annotations

import hashlib
import sqlite3
from functools import wraps
from typing import Any

from flask import current_app, g


def hash_password(password: str) -> str:
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        path = current_app.config["DATABASE"]
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS master_usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.commit()
    row = db.execute("SELECT COUNT(*) AS n FROM master_usuarios").fetchone()
    if int(row["n"] or 0) == 0:
        email = (current_app.config.get("SEED_EMAIL") or "").strip().lower()
        password = current_app.config.get("SEED_PASSWORD") or ""
        if email and password:
            db.execute(
                "INSERT INTO master_usuarios (email, password, nombre) VALUES (?, ?, ?)",
                (email, hash_password(password), "Administrador"),
            )
            db.commit()


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    email_n = (email or "").strip().lower()
    if not email_n or not password:
        return None
    row = get_db().execute(
        """
        SELECT id, email, nombre
        FROM master_usuarios
        WHERE lower(email) = ? AND password = ? AND activo = 1
        """,
        (email_n, hash_password(password)),
    ).fetchone()
    return dict(row) if row else None


def with_app_context_db(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper
