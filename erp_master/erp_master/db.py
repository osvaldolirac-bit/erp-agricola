from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from functools import wraps
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, g

ROLES_MASTER = ("super_admin", "admin")
ROL_LABEL = {
    "super_admin": "Super Administrador",
    "admin": "Administrador",
}

_TZ_CHILE = ZoneInfo("America/Santiago")


def now_chile() -> str:
    return datetime.now(_TZ_CHILE).strftime("%Y-%m-%d %H:%M:%S")


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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS master_usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            rol TEXT NOT NULL DEFAULT 'admin',
            tenant_slug TEXT DEFAULT '',
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT DEFAULT (datetime('now'))
        )
        """
    )
    cols = _column_names(db, "master_usuarios")
    for col, ddl in (
        ("rol", "ALTER TABLE master_usuarios ADD COLUMN rol TEXT NOT NULL DEFAULT 'admin'"),
        ("tenant_slug", "ALTER TABLE master_usuarios ADD COLUMN tenant_slug TEXT DEFAULT ''"),
    ):
        if col in cols:
            continue
        try:
            db.execute(ddl)
        except sqlite3.OperationalError as exc:
            # Carrera entre workers gunicorn al migrar
            if "duplicate column" not in str(exc).lower():
                raise
        cols = _column_names(db, "master_usuarios")
    # Promote legacy single seed user to super_admin
    db.execute(
        """
        UPDATE master_usuarios
        SET rol = 'super_admin', tenant_slug = '',
            nombre = CASE WHEN nombre IN ('', 'Administrador') THEN 'Super Administrador' ELSE nombre END
        WHERE id = (
            SELECT id FROM master_usuarios ORDER BY id LIMIT 1
        )
        AND (rol IS NULL OR rol = '' OR rol = 'admin')
        AND (
            SELECT COUNT(*) FROM master_usuarios
        ) = 1
        """
    )
    # Any empty rol → admin
    db.execute(
        "UPDATE master_usuarios SET rol = 'admin' WHERE rol IS NULL OR rol = ''"
    )
    db.commit()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS master_bitacora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL,
            usuario TEXT NOT NULL DEFAULT '',
            accion TEXT NOT NULL DEFAULT '',
            detalle TEXT NOT NULL DEFAULT '',
            fecha_hora TEXT NOT NULL
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_master_bitacora_tenant_fecha "
        "ON master_bitacora (tenant_slug, fecha_hora DESC)"
    )
    db.commit()

    row = db.execute("SELECT COUNT(*) AS n FROM master_usuarios").fetchone()
    if int(row["n"] or 0) == 0:
        email = (current_app.config.get("SEED_EMAIL") or "").strip().lower()
        password = current_app.config.get("SEED_PASSWORD") or ""
        if email and password:
            db.execute(
                """
                INSERT INTO master_usuarios (email, password, nombre, rol, tenant_slug)
                VALUES (?, ?, ?, 'super_admin', '')
                """,
                (email, hash_password(password), "Super Administrador"),
            )
            db.commit()


def log_bitacora(
    tenant_slug: str,
    usuario: str,
    accion: str,
    detalle: str = "",
) -> None:
    """Registra un movimiento de Super Consola por tenant (no va a la bitácora del ERP)."""
    slug = (tenant_slug or "").strip().lower()
    if not slug:
        return
    try:
        get_db().execute(
            """
            INSERT INTO master_bitacora (tenant_slug, usuario, accion, detalle, fecha_hora)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                slug,
                (usuario or "").strip() or "consola",
                (accion or "").strip() or "ACCION",
                (detalle or "").strip(),
                now_chile(),
            ),
        )
        get_db().commit()
    except Exception:
        pass


def list_bitacora(tenant_slug: str, limit: int = 200) -> list[dict[str, Any]]:
    slug = (tenant_slug or "").strip().lower()
    if not slug:
        return []
    try:
        lim = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        lim = 200
    rows = get_db().execute(
        """
        SELECT id, usuario, accion, detalle, fecha_hora
        FROM master_bitacora
        WHERE tenant_slug = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (slug, lim),
    ).fetchall()
    return [dict(r) for r in rows]


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    email_n = (email or "").strip().lower()
    if not email_n or not password:
        return None
    row = get_db().execute(
        """
        SELECT id, email, nombre, rol, tenant_slug
        FROM master_usuarios
        WHERE lower(email) = ? AND password = ? AND activo = 1
        """,
        (email_n, hash_password(password)),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get("rol") not in ROLES_MASTER:
        data["rol"] = "admin"
    data["rol_label"] = ROL_LABEL.get(data["rol"], data["rol"])
    return data


def list_master_users() -> list[dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT id, email, nombre, rol, tenant_slug, activo, creado_en
        FROM master_usuarios
        ORDER BY CASE rol WHEN 'super_admin' THEN 0 ELSE 1 END, lower(email)
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["rol_label"] = ROL_LABEL.get(d.get("rol") or "", d.get("rol") or "")
        out.append(d)
    return out


def create_master_user(
    email: str,
    password: str,
    nombre: str,
    rol: str,
    tenant_slug: str = "",
) -> tuple[bool, str]:
    email_n = (email or "").strip().lower()
    if not email_n or "@" not in email_n:
        return False, "Correo inválido."
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    if rol not in ROLES_MASTER:
        return False, "Rol de consola inválido."
    tenant_slug = (tenant_slug or "").strip()
    if rol == "admin" and not tenant_slug:
        return False, "El Administrador debe tener un ERP asignado."
    if rol == "super_admin":
        tenant_slug = ""
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM master_usuarios WHERE lower(email) = ?", (email_n,)
    ).fetchone()
    if exists:
        return False, "Ya existe un usuario de consola con ese correo."
    db.execute(
        """
        INSERT INTO master_usuarios (email, password, nombre, rol, tenant_slug, activo)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (
            email_n,
            hash_password(password),
            (nombre or "").strip() or ROL_LABEL.get(rol, rol),
            rol,
            tenant_slug,
        ),
    )
    db.commit()
    return True, "Usuario de consola creado."


def set_master_user_activo(user_id: int, activo: bool) -> tuple[bool, str]:
    db = get_db()
    row = db.execute(
        "SELECT id, rol FROM master_usuarios WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return False, "Usuario no encontrado."
    if row["rol"] == "super_admin" and not activo:
        n = db.execute(
            "SELECT COUNT(*) AS n FROM master_usuarios WHERE rol = 'super_admin' AND activo = 1"
        ).fetchone()["n"]
        if int(n) <= 1:
            return False, "No se puede desactivar el último Super Administrador."
    db.execute(
        "UPDATE master_usuarios SET activo = ? WHERE id = ?",
        (1 if activo else 0, user_id),
    )
    db.commit()
    return True, "Estado actualizado."


def change_master_password(user_id: int, password: str) -> tuple[bool, str]:
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    db = get_db()
    row = db.execute(
        "SELECT id FROM master_usuarios WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return False, "Usuario no encontrado."
    db.execute(
        "UPDATE master_usuarios SET password = ? WHERE id = ?",
        (hash_password(password), user_id),
    )
    db.commit()
    return True, "Clave de consola actualizada."


def delete_master_user(user_id: int) -> tuple[bool, str]:
    db = get_db()
    row = db.execute(
        "SELECT id, rol FROM master_usuarios WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return False, "Usuario no encontrado."
    if row["rol"] == "super_admin":
        n = db.execute(
            "SELECT COUNT(*) AS n FROM master_usuarios WHERE rol = 'super_admin' AND activo = 1"
        ).fetchone()["n"]
        if int(n) <= 1:
            return False, "No se puede eliminar el último Super Administrador."
    db.execute("DELETE FROM master_usuarios WHERE id = ?", (user_id,))
    db.commit()
    return True, "Usuario de consola eliminado."


def with_app_context_db(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper
