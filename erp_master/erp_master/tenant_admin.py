"""Administración de ERP tenants (LC / DEMO) desde la consola master.

Lee/escribe SQLite de cada tenant. No toca Río Maipo ni fusiona código.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from flask import current_app

DEMO_DIAS_PRUEBA_DEFAULT = 30
DEMO_LOGIN_URL = os.environ.get("ERP_AGRICOLA_LOGIN_URL", "https://erpmaster.cl/agricola/login")
DEMO_WEB_ROOT = os.environ.get("ERP_DEMO_WEB_ROOT", "/root/demo-web")

FRECUENCIAS = ("diario", "semanal", "mensual")

MENU_LC = [
    ("DASHBOARD", "Dashboard"),
    ("Compras", "Compras"),
    ("Tesoreria", "Tesorería"),
    ("Flujo financiero", "Flujo financiero"),
    ("Costos", "Costos"),
    ("RRHH", "RRHH"),
    ("Espino", "El Espino"),
    ("Libro de Campo", "Libro de Campo"),
    ("Petróleo", "Petróleo"),
    ("Riego", "Riego"),
    ("Bodega", "Bodega"),
    ("Maquinaria", "Maquinaria"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),
    ("Manual", "Manual"),
]

MENU_DEMO = [
    ("DASHBOARD", "Dashboard"),
    ("Compras", "Compras"),
    ("Tesoreria", "Tesorería"),
    ("Flujo financiero", "Flujo financiero"),
    ("Costos", "Costos"),
    ("RRHH", "RRHH"),
    ("Campob", "Campo B"),
    ("Libro de Campo", "Libro de Campo"),
    ("Petróleo", "Petróleo"),
    ("Riego", "Riego"),
    ("Bodega", "Bodega"),
    ("Maquinaria", "Maquinaria"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),
    ("Manual", "Manual"),
]

ROLES_LC = ("admin", "operador", "certificacion", "lector")
ROLES_DEMO = ("super_admin", "admin_cliente", "admin", "operador", "certificacion")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str, kind: str) -> str:
    raw = str(password or "")
    if kind == "lc":
        raw = raw.strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def menu_for(kind: str) -> list[tuple[str, str]]:
    return list(MENU_LC if kind == "lc" else MENU_DEMO)


def roles_for(kind: str) -> tuple[str, ...]:
    return ROLES_LC if kind == "lc" else ROLES_DEMO


def protected_role(kind: str) -> str:
    return "admin" if kind == "lc" else "super_admin"


@contextmanager
def tenant_conn(db_path: str):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _meta_get(conn: sqlite3.Connection, clave: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave = ?", (clave,)
    ).fetchone()
    return (row["valor"] if row and row["valor"] is not None else default) or default


def _meta_set(conn: sqlite3.Connection, clave: str, valor: str) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta (clave, valor) VALUES (?, ?)
        ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor
        """,
        (clave, valor),
    )


def _ensure_mail_riego_bitacora(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "mail_riego_bitacora" not in cols:
        conn.execute(
            "ALTER TABLE usuarios ADD COLUMN mail_riego_bitacora INTEGER DEFAULT 0"
        )


def list_users(db_path: str, kind: str) -> list[dict[str, Any]]:
    with tenant_conn(db_path) as conn:
        _ensure_mail_riego_bitacora(conn)
        if kind == "demo":
            rows = conn.execute(
                """
                SELECT id, email, rol, modulos, mail_tesoreria,
                       COALESCE(mail_riego_bitacora, 0) AS mail_riego_bitacora,
                       fecha_expira, invitado_por
                FROM usuarios
                ORDER BY lower(email)
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, email, rol, modulos, mail_tesoreria,
                       solo_lectura, mail_petroleo_bitacora,
                       COALESCE(mail_riego_bitacora, 0) AS mail_riego_bitacora
                FROM usuarios
                ORDER BY lower(email)
                """
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        mods = (d.get("modulos") or "").strip()
        d["modulos_txt"] = "Todos" if not mods else mods
        d["es_operador"] = (d.get("rol") or "") in {"operador", "lector"}
        out.append(d)
    return out


def _ensure_demo_web_path() -> None:
    root = (DEMO_WEB_ROOT or "").strip()
    if root and root not in sys.path and os.path.isdir(root):
        sys.path.insert(0, root)


def create_user(
    db_path: str,
    kind: str,
    email: str,
    password: str,
    rol: str,
    *,
    dias_demo: int = 30,
    invitado_por: str = "",
    enviar_invitacion: bool = True,
) -> tuple[bool, str]:
    email_n = (email or "").strip().lower()
    if not email_n or not _EMAIL_RE.match(email_n):
        return False, "Correo inválido."
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    if rol not in roles_for(kind):
        return False, "Rol no válido para este ERP."
    exp = ""
    with tenant_conn(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM usuarios WHERE lower(email) = ?", (email_n,)
        ).fetchone()
        if exists:
            return False, "Ya existe un usuario con ese correo."
        pwd = hash_password(password, kind)
        if kind == "demo":
            exp = (date.today() + timedelta(days=max(1, int(dias_demo)))).isoformat()
            conn.execute(
                """
                INSERT INTO usuarios
                  (email, password, rol, fecha_expira, invitado_por, modulos)
                VALUES (?, ?, ?, ?, ?, '')
                """,
                (email_n, pwd, rol, exp, (invitado_por or "").strip()),
            )
        else:
            conn.execute(
                """
                INSERT INTO usuarios (email, password, rol, modulos)
                VALUES (?, ?, ?, '')
                """,
                (email_n, pwd, rol),
            )
    msg = "Usuario creado."
    if kind == "demo":
        msg = f"Usuario creado. Vigencia hasta {exp}."
        if enviar_invitacion:
            ok_mail, mail_txt = send_demo_invitation(
                db_path,
                email_n,
                password,
                rol,
                invitado_por or "",
                exp,
            )
            msg = f"{msg} {mail_txt}"
            if not ok_mail:
                return True, msg
    return True, msg


def send_demo_invitation(
    db_path: str,
    email: str,
    password_plain: str,
    rol: str,
    admin_email: str,
    fecha_expira: str,
) -> tuple[bool, str]:
    """Envía correo de invitación demo (usa helpers de app_demo)."""
    try:
        _ensure_demo_web_path()
        import app_demo as demo  # noqa: WPS433

        demo.NOMBRE_DB = db_path
        # Acceso unificado del rubro agrícola
        demo.DEMO_URL = DEMO_LOGIN_URL
        res = demo.enviar_correo_invitacion_demo(
            email, password_plain, rol, admin_email, fecha_expira
        )
        ok = bool(res.get("invitado")) if isinstance(res, dict) else bool(res)
        if ok:
            return True, f"Correo de invitación enviado a {email}."
        return False, "No se pudo enviar el correo de invitación (revise SMTP)."
    except Exception as exc:
        return False, f"Invitación no enviada: {exc}"


def get_plataforma_demo(db_path: str) -> dict[str, Any]:
    """Resumen de plataforma demo (antes en Administración ERP)."""
    _ensure_demo_web_path()
    seed_version = "demo_datos_v6"
    try:
        from demo_seed import DEMO_SEED_VERSION  # noqa: WPS433

        seed_version = DEMO_SEED_VERSION
    except Exception:
        pass

    with tenant_conn(db_path) as conn:
        try:
            import app_demo as demo  # noqa: WPS433

            demo.NOMBRE_DB = db_path
            n_super, n_cliente = demo.contar_roles_admin_demo(conn)
            dias = int(getattr(demo, "DEMO_DIAS_PRUEBA", DEMO_DIAS_PRUEBA_DEFAULT))
        except Exception:
            n_super = conn.execute(
                "SELECT COUNT(*) AS n FROM usuarios WHERE rol='super_admin'"
            ).fetchone()["n"]
            n_cliente = conn.execute(
                "SELECT COUNT(*) AS n FROM usuarios WHERE rol='admin_cliente'"
            ).fetchone()["n"]
            dias = DEMO_DIAS_PRUEBA_DEFAULT
        seed_ok = bool(
            conn.execute(
                "SELECT 1 FROM schema_meta WHERE clave=? AND valor='1'",
                (seed_version,),
            ).fetchone()
        )
        rows = conn.execute(
            """
            SELECT email, COALESCE(rol,'operador') AS rol,
                   fecha_expira, COALESCE(invitado_por,'') AS invitado_por
            FROM usuarios
            ORDER BY lower(email)
            """
        ).fetchall()
        try:
            n_bit = conn.execute("SELECT COUNT(*) AS n FROM bitacora").fetchone()["n"]
        except Exception:
            n_bit = 0
    usuarios = []
    for r in rows:
        perfil = r["rol"]
        try:
            import app_demo as demo  # noqa: WPS433

            perfil = demo.etiqueta_perfil_demo(r["rol"], r["email"])
        except Exception:
            pass
        usuarios.append(
            {
                "email": r["email"],
                "perfil": perfil,
                "vigencia": "Permanente" if not r["fecha_expira"] else str(r["fecha_expira"])[:10],
                "invitado_por": r["invitado_por"] or "",
            }
        )
    return {
        "n_super": int(n_super or 0),
        "n_cliente": int(n_cliente or 0),
        "dias_prueba": dias,
        "seed_version": seed_version,
        "seed_ok": seed_ok,
        "nombre_db": db_path,
        "login_url": DEMO_LOGIN_URL,
        "usuarios_plat": usuarios,
        "bitacora_activa": get_bitacora_erp("demo"),
        "bitacora_registros": int(n_bit or 0),
    }


def reseed_demo(db_path: str) -> tuple[bool, str]:
    """Re-siembra datos ficticios del DEMO (no borra usuarios)."""
    try:
        _ensure_demo_web_path()
        from demo_seed import DEMO_SEED_VERSION, sembrar_datos_demo, vaciar_datos_demo
        import app_demo as demo  # noqa: WPS433

        demo.NOMBRE_DB = db_path
        with tenant_conn(db_path) as conn:
            cur = conn.cursor()
            vaciar_datos_demo(cur)
            h = demo.hora_chile().date()
            sembrar_datos_demo(
                cur,
                h,
                demo.hora_chile().strftime("%m"),
                demo.hora_chile().year,
                demo.PRORRATEO_RRHH,
                demo.CENTROS_COSTO,
                demo.CUARTELES_PRORRATEO,
                demo.TEMPORADAS_COSTOS,
                demo.RAZONES_SOCIALES_COMPRAS[0],
                demo.TIPO_GASTO_SIN_CLASIFICAR,
                demo.hora_chile,
            )
            cur.execute(
                "INSERT OR REPLACE INTO schema_meta (clave, valor) VALUES (?, '1')",
                (DEMO_SEED_VERSION,),
            )
            # DEMO: bitácora queda en cero salvo que Master la active.
            try:
                cur.execute("DELETE FROM bitacora")
            except Exception:
                pass
            if get_bitacora_erp("demo"):
                try:
                    cur.execute(
                        "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                        (
                            "MASTER",
                            "DEMO RESEED",
                            DEMO_SEED_VERSION,
                            demo.hora_chile().strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )
                except Exception:
                    pass
            else:
                set_bitacora_erp("demo", False)
        return True, "Datos ficticios re-sembrados."
    except Exception as exc:
        return False, f"No se pudo re-sembrar: {exc}"


def change_role(db_path: str, kind: str, user_id: int, rol: str) -> tuple[bool, str]:
    if rol not in roles_for(kind):
        return False, "Rol no válido."
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, rol FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        prot = protected_role(kind)
        if row["rol"] == prot and rol != prot:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM usuarios WHERE rol = ?", (prot,)
            ).fetchone()["n"]
            if int(n) <= 1:
                return False, f"No se puede quitar el último {prot}."
        conn.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (rol, user_id))
    return True, "Rol actualizado."


def change_password(
    db_path: str, kind: str, user_id: int, password: str
) -> tuple[bool, str]:
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        conn.execute(
            "UPDATE usuarios SET password = ? WHERE id = ?",
            (hash_password(password, kind), user_id),
        )
    return True, "Clave actualizada."


def delete_user(db_path: str, kind: str, user_id: int) -> tuple[bool, str]:
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, rol FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        prot = protected_role(kind)
        if row["rol"] == prot:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM usuarios WHERE rol = ?", (prot,)
            ).fetchone()["n"]
            if int(n) <= 1:
                return False, f"No se puede eliminar el último {prot}."
        conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    return True, "Usuario eliminado."


def set_mail_flags(
    db_path: str,
    kind: str,
    user_id: int,
    *,
    mail_tesoreria: bool | None = None,
    mail_petroleo: bool | None = None,
    mail_riego: bool | None = None,
    solo_lectura: bool | None = None,
) -> tuple[bool, str]:
    with tenant_conn(db_path) as conn:
        _ensure_mail_riego_bitacora(conn)
        row = conn.execute(
            "SELECT id FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        if mail_tesoreria is not None:
            conn.execute(
                "UPDATE usuarios SET mail_tesoreria = ? WHERE id = ?",
                (1 if mail_tesoreria else 0, user_id),
            )
        if mail_riego is not None:
            conn.execute(
                "UPDATE usuarios SET mail_riego_bitacora = ? WHERE id = ?",
                (1 if mail_riego else 0, user_id),
            )
        if kind == "lc":
            if mail_petroleo is not None:
                conn.execute(
                    "UPDATE usuarios SET mail_petroleo_bitacora = ? WHERE id = ?",
                    (1 if mail_petroleo else 0, user_id),
                )
            if solo_lectura is not None:
                conn.execute(
                    "UPDATE usuarios SET solo_lectura = ? WHERE id = ?",
                    (1 if solo_lectura else 0, user_id),
                )
    return True, "Preferencias actualizadas."


def get_user_modules(db_path: str, user_id: int) -> tuple[str, list[str], bool]:
    """Returns email, selected keys, all_modules flag."""
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT email, modulos, rol FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
    if not row:
        return "", [], True
    raw = (row["modulos"] or "").strip()
    if not raw:
        return row["email"], [], True
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return row["email"], keys, False


def save_user_modules(
    db_path: str, kind: str, user_id: int, selected: list[str]
) -> tuple[bool, str]:
    valid = {k for k, _ in menu_for(kind)}
    chosen = [k for k in selected if k in valid]
    # Empty selection or full set → store "" (all modules)
    if not chosen or set(chosen) >= valid:
        value = ""
    else:
        value = ",".join(chosen)
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id, rol FROM usuarios WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        if row["rol"] not in {"operador", "lector"}:
            return False, "Los módulos solo aplican a operador/lector."
        conn.execute(
            "UPDATE usuarios SET modulos = ? WHERE id = ?", (value, user_id)
        )
    return True, "Módulos guardados."


def get_respaldo_config(db_path: str) -> dict[str, str]:
    with tenant_conn(db_path) as conn:
        return {
            "email": _meta_get(conn, "respaldo_email"),
            "activo": _meta_get(conn, "respaldo_activo", "0"),
            "frecuencia": _meta_get(conn, "respaldo_frecuencia", "diario"),
            "codigo_frecuencia": _meta_get(
                conn, "respaldo_codigo_frecuencia", "semanal"
            ),
            "ultimo_envio": _meta_get(conn, "respaldo_ultimo_envio"),
            "ultimo_error": _meta_get(conn, "respaldo_ultimo_error"),
            "codigo_ultimo_envio": _meta_get(conn, "respaldo_codigo_ultimo_envio"),
            "codigo_ultimo_error": _meta_get(conn, "respaldo_codigo_ultimo_error"),
        }


def save_respaldo_config(
    db_path: str,
    email: str,
    activo: bool,
    freq_datos: str,
    freq_codigo: str,
) -> tuple[bool, str]:
    email_n = (email or "").strip()
    if freq_datos not in FRECUENCIAS:
        freq_datos = "diario"
    if freq_codigo not in FRECUENCIAS:
        freq_codigo = "semanal"
    if activo:
        parts = [p.strip() for p in email_n.replace(";", ",").split(",") if p.strip()]
        if not parts or not all(_EMAIL_RE.match(p) for p in parts):
            return False, "Correo destino inválido para activar el respaldo."
    with tenant_conn(db_path) as conn:
        _meta_set(conn, "respaldo_email", email_n)
        _meta_set(conn, "respaldo_activo", "1" if activo else "0")
        _meta_set(conn, "respaldo_frecuencia", freq_datos)
        _meta_set(conn, "respaldo_codigo_frecuencia", freq_codigo)
    return True, "Configuración de respaldo guardada."


def _status_dir() -> str:
    try:
        return current_app.config.get("STATUS_DIR") or "/root/erp_status"
    except RuntimeError:
        return os.environ.get("ERP_STATUS_DIR", "/root/erp_status").strip() or "/root/erp_status"


def _mantenimiento_path(slug: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())
    return os.path.join(_status_dir(), f"{safe}.mantenimiento")


def get_mantenimiento(slug: str) -> bool:
    path = _mantenimiento_path(slug)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _bump_session_epoch(slug: str) -> None:
    """Invalida sesiones del ERP para volver a pantalla de acceso al restaurar."""
    path = os.path.join(_status_dir(), f"{slug}.session_epoch")
    try:
        cur = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cur = int((f.read().strip() or "0") or "0")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{cur + 1}\n")
    except (OSError, ValueError):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("1\n")
        except OSError:
            pass


def _bitacora_erp_path(slug: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())
    return os.path.join(_status_dir(), f"{safe}.bitacora")


def get_bitacora_erp(slug: str) -> bool:
    path = _bitacora_erp_path(slug)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def set_bitacora_erp(slug: str, activo: bool) -> tuple[bool, str]:
    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())
    if not safe:
        return False, "Cliente inválido."
    path = _bitacora_erp_path(safe)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1\n" if activo else "0\n")
    except OSError as exc:
        return False, f"No se pudo actualizar bitácora ERP: {exc}"
    return True, "Bitácora ERP activada." if activo else "Bitácora ERP desactivada (en cero)."


def clear_bitacora_erp(db_path: str) -> tuple[bool, str]:
    """Vacía la tabla bitácora operativa del tenant."""
    try:
        with tenant_conn(db_path) as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM bitacora").fetchone()["n"]
            conn.execute("DELETE FROM bitacora")
        return True, f"Bitácora ERP vaciada ({int(n or 0)} registros eliminados)."
    except Exception as exc:
        return False, f"No se pudo vaciar bitácora: {exc}"


def set_mantenimiento(slug: str, activo: bool) -> tuple[bool, str]:
    safe = re.sub(r"[^a-z0-9_-]+", "", (slug or "").strip().lower())
    if not safe:
        return False, "Cliente inválido."
    path = _mantenimiento_path(safe)
    post_path = os.path.join(_status_dir(), f"{safe}.post_maint")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1\n" if activo else "0\n")
        # Al activar o restaurar, fuerza re-acceso en el ERP.
        _bump_session_epoch(safe)
        # Al restaurar: siguiente visita = login limpio y luego dashboard.
        with open(post_path, "w", encoding="utf-8") as f:
            f.write("0\n" if activo else "1\n")
    except OSError as exc:
        return False, f"No se pudo actualizar mantención: {exc}"
    estado = "activado" if activo else "desactivado"
    return True, f"Sitio en mantención {estado}."


# Defaults de CC prorrateables (Master no depende de app_demo/app_concepcion).
_PRORRATEO_DEFAULTS: dict[str, dict[str, Any]] = {
    "demo": {
        "cuarteles": [
            "CUARTEL A",
            "CUARTEL B",
            "CUARTEL C",
            "CUARTEL D",
            "CUARTEL E",
            "CUARTEL F",
        ],
        "default_pct": {},
        "directos": ["CAMPO B"],
    },
    "lc": {
        "cuarteles": [
            "CEREZOS CORTE 1",
            "CEREZOS CORTE 2",
            "CIRUELOS",
            "NOGALES APARICION",
            "NOGALES CRUZ DEL SUR",
        ],
        "default_pct": {
            "CEREZOS CORTE 1": 7.94,
            "CEREZOS CORTE 2": 7.94,
            "CIRUELOS": 32.71,
            "NOGALES APARICION": 32.71,
            "NOGALES CRUZ DEL SUR": 18.70,
        },
        "default_ha": {
            "CEREZOS CORTE 1": 1.7,
            "CEREZOS CORTE 2": 1.7,
            "CIRUELOS": 7.0,
            "NOGALES APARICION": 7.0,
            "NOGALES CRUZ DEL SUR": 4.0,
        },
        "directos": ["EL ESPINO", "OTROS"],
    },
}


def _prorrateo_meta(kind: str) -> dict[str, Any]:
    return dict(_PRORRATEO_DEFAULTS.get(kind) or _PRORRATEO_DEFAULTS["demo"])


def _ensure_prorrateo_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prorrateo_cc (
            centro_costo TEXT PRIMARY KEY,
            porcentaje REAL NOT NULL,
            superficie_ha REAL DEFAULT 0
        )"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
    if "superficie_ha" not in cols:
        try:
            conn.execute(
                "ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0"
            )
        except Exception:
            pass


def get_prorrateo_cc(db_path: str, kind: str) -> dict[str, Any]:
    """Prorrateo % y superficie (ha) por centro de costo."""
    meta = _prorrateo_meta(kind)
    cuarteles = list(meta["cuarteles"])
    default = dict(meta.get("default_pct") or {})
    default_ha = dict(meta.get("default_ha") or {})
    with tenant_conn(db_path) as conn:
        _ensure_prorrateo_table(conn)
        rows = conn.execute(
            """SELECT centro_costo, porcentaje, COALESCE(superficie_ha, 0)
               FROM prorrateo_cc ORDER BY centro_costo"""
        ).fetchall()
        pcts = {str(r[0]): float(r[1]) for r in rows} if rows else dict(default)
        has_ha = {str(r[0]): float(r[2] or 0) for r in rows} if rows else {}
        extras = [cc for cc in pcts if cc not in cuarteles]
        if extras:
            cuarteles = cuarteles + sorted(extras)
    rows_out = []
    for cc in cuarteles:
        ha_val = has_ha.get(cc)
        if ha_val is None or ha_val <= 0:
            ha_val = float(default_ha.get(cc, 0) or 0)
        rows_out.append(
            {
                "cc": cc,
                "nombre": str(cc).title() if str(cc).isupper() else str(cc),
                "porcentaje": float(pcts.get(cc, default.get(cc, 0)) or 0),
                "superficie_ha": float(ha_val or 0),
            }
        )
    suma = sum(r["porcentaje"] for r in rows_out)
    return {
        "rows": rows_out,
        "suma": suma,
        "ok": abs(suma - 100.0) < 0.05,
        "directos": list(meta.get("directos") or []),
    }


def save_prorrateo_cc(
    db_path: str,
    kind: str,
    porcentajes: dict[str, float],
    superficies: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """Guarda % (suma 100) y superficie ha por CC."""
    _ = kind
    if not porcentajes:
        return False, "Sin centros de costo."
    try:
        vals = {str(k): float(v) for k, v in porcentajes.items()}
    except (TypeError, ValueError):
        return False, "Porcentajes inválidos."
    if any(v < 0 for v in vals.values()):
        return False, "No se permiten porcentajes negativos."
    suma = sum(vals.values())
    if abs(suma - 100.0) >= 0.05:
        return False, f"Los porcentajes deben sumar 100 % (suma actual: {suma:.2f} %)."

    with tenant_conn(db_path) as conn:
        _ensure_prorrateo_table(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(prorrateo_cc)").fetchall()}
        has_ha = "superficie_ha" in cols
        ha_map: dict[str, float] = {}
        if has_ha:
            for r in conn.execute(
                "SELECT centro_costo, COALESCE(superficie_ha, 0) FROM prorrateo_cc"
            ).fetchall():
                ha_map[str(r[0])] = float(r[1] or 0)

        superficies = superficies or {}
        for cc, pct in vals.items():
            ha = float(superficies.get(cc, ha_map.get(cc, 0)) or 0)
            if has_ha:
                conn.execute(
                    """INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha)
                       VALUES (?,?,?)
                       ON CONFLICT(centro_costo) DO UPDATE SET
                         porcentaje=excluded.porcentaje,
                         superficie_ha=excluded.superficie_ha""",
                    (cc, float(pct), ha),
                )
            else:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct)),
                )
    detalle = ", ".join(f"{k}={v:.2f}%" for k, v in vals.items())
    return True, f"Prorrateo CC guardado ({detalle})."
