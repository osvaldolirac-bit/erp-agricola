"""Consultas usuarios compatibles demo (fecha_expira) vs La Concepción."""
from __future__ import annotations

import sqlite3


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def usuario_cols(conn: sqlite3.Connection) -> set[str]:
    return _cols(conn, "usuarios")


def has_fecha_expira(conn: sqlite3.Connection) -> bool:
    return "fecha_expira" in usuario_cols(conn)


def has_invitado_por(conn: sqlite3.Connection) -> bool:
    return "invitado_por" in usuario_cols(conn)


def fetch_login_row(conn: sqlite3.Connection, email: str, password_hash: str):
    if has_fecha_expira(conn):
        return conn.execute(
            """SELECT email, COALESCE(rol,'operador'), fecha_expira
               FROM usuarios WHERE lower(email)=lower(?) AND password=?""",
            (email, password_hash),
        ).fetchone()
    return conn.execute(
        """SELECT email, COALESCE(rol,'operador'), NULL
           FROM usuarios WHERE lower(email)=lower(?) AND password=?""",
        (email, password_hash),
    ).fetchone()


def fetch_session_row(conn: sqlite3.Connection, email: str):
    cols = _cols(conn, "usuarios")
    if "solo_lectura" in cols and "fecha_expira" in cols:
        return conn.execute(
            "SELECT COALESCE(rol,'operador'), fecha_expira, COALESCE(solo_lectura,0) FROM usuarios WHERE lower(email)=lower(?)",
            (email,),
        ).fetchone()
    if "solo_lectura" in cols:
        return conn.execute(
            "SELECT COALESCE(rol,'operador'), NULL, COALESCE(solo_lectura,0) FROM usuarios WHERE lower(email)=lower(?)",
            (email,),
        ).fetchone()
    if "fecha_expira" in cols:
        return conn.execute(
            "SELECT COALESCE(rol,'operador'), fecha_expira FROM usuarios WHERE lower(email)=lower(?)",
            (email,),
        ).fetchone()
    return conn.execute(
        "SELECT COALESCE(rol,'operador'), NULL FROM usuarios WHERE lower(email)=lower(?)",
        (email,),
    ).fetchone()


def fetch_bridge_user(conn: sqlite3.Connection, email: str):
    """Usuario para ingreso desde Super Consola: (email, rol, fecha_expira)."""
    if has_fecha_expira(conn):
        return conn.execute(
            """SELECT email, COALESCE(rol,'operador'), fecha_expira
               FROM usuarios WHERE lower(email)=lower(?)""",
            (email,),
        ).fetchone()
    return conn.execute(
        """SELECT email, COALESCE(rol,'operador'), NULL
           FROM usuarios WHERE lower(email)=lower(?)""",
        (email,),
    ).fetchone()
