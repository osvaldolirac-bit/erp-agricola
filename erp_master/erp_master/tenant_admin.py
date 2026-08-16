"""Administración de ERP tenants (LC / DEMO / Comercial) desde la consola master.

Lee/escribe SQLite de cada tenant.
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
from erp_master.db import hoy_chile

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
    ("Bodega", "Bodega"),
    ("Maquinaria", "Maquinaria"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),  # usuarios reportan; inbox vive en Super Consola
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
    ("Bodega", "Bodega"),
    ("Maquinaria", "Maquinaria"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),  # usuarios reportan; inbox vive en Super Consola
    ("Manual", "Manual"),
]

ROLES_LC = ("admin", "operador", "certificacion", "lector")
ROLES_DEMO = ("super_admin", "admin_cliente", "admin", "operador", "certificacion")
ROLES_COMERCIAL = ("Administrador", "Operador", "Consulta")
MENU_COMERCIAL: list[tuple[str, str]] = []  # sin módulos tipo agrícola

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")



def _parse_invitado_meta(invitado_por: str | None) -> tuple[str, str]:
    """Separa origen (ig:tel) y plan de interés (contratar:ventas)."""
    raw = (invitado_por or "").strip()
    if not raw:
        return "", ""
    origen = ""
    plan = ""
    for part in raw.split("|"):
        part = part.strip()
        if part.startswith("contratar:"):
            key = part.split(":", 1)[-1].strip().lower()
            plan = {
                "modulos": "Quiere contratar: Por módulo",
                "ventas": "Quiere contratar: Pack Ventas",
                "compras": "Quiere contratar: Pack Compras",
                "comercial": "Quiere contratar: Pack Comercial",
            }.get(key, f"Quiere contratar: {key}")
        elif part:
            origen = part
    return origen, plan



def _status_usuario_prueba(fecha_expira: str | None, plan_interes: str | None = None) -> dict[str, str]:
    """Un solo eje de estado para listados de usuarios (evita módulos duplicados)."""
    raw = str(fecha_expira or "").strip()[:10]
    plan = (plan_interes or "").strip()
    if not raw:
        return {
            "status": "alta",
            "status_label": "Alta / permanente",
            "status_tone": "ok",
        }
    try:
        fexp = date.fromisoformat(raw)
    except ValueError:
        return {
            "status": "prueba",
            "status_label": "En prueba",
            "status_tone": "warn",
        }
    hoy = date.today()
    if fexp < hoy:
        st = {
            "status": "vencido",
            "status_label": "Prueba vencida",
            "status_tone": "danger",
        }
    else:
        dias = (fexp - hoy).days
        st = {
            "status": "prueba",
            "status_label": f"En prueba ({dias}d)" if dias > 0 else "En prueba (hoy)",
            "status_tone": "warn",
        }
    if plan:
        st["status_label"] = f"{st['status_label']} · {plan}"
    return st


def hash_password(password: str, kind: str) -> str:
    raw = str(password or "")
    if kind == "lc":
        raw = raw.strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def menu_for(kind: str) -> list[tuple[str, str]]:
    if kind == "lc":
        return list(MENU_LC)
    if kind == "comercial":
        return list(MENU_COMERCIAL)
    return list(MENU_DEMO)


def roles_for(kind: str) -> tuple[str, ...]:
    if kind == "lc":
        return ROLES_LC
    if kind == "comercial":
        return ROLES_COMERCIAL
    return ROLES_DEMO


def protected_role(kind: str) -> str:
    if kind == "lc":
        return "admin"
    if kind == "comercial":
        return "Administrador"
    return "super_admin"


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


def _ensure_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
    )


def _meta_get(conn: sqlite3.Connection, clave: str, default: str = "") -> str:
    _ensure_schema_meta(conn)
    row = conn.execute(
        "SELECT valor FROM schema_meta WHERE clave = ?", (clave,)
    ).fetchone()
    return (row["valor"] if row and row["valor"] is not None else default) or default


def _meta_set(conn: sqlite3.Connection, clave: str, valor: str) -> None:
    _ensure_schema_meta(conn)
    conn.execute(
        """
        INSERT INTO schema_meta (clave, valor) VALUES (?, ?)
        ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor
        """,
        (clave, valor),
    )


def list_users(db_path: str, kind: str) -> list[dict[str, Any]]:
    with tenant_conn(db_path) as conn:
        if kind == "comercial":
            cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
            for col, decl in (
                ("fecha_expira", "TEXT"),
                ("invitado_por", "TEXT"),
                ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
                ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
            ):
                if col not in cols:
                    conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {decl}")
            rows = conn.execute(
                """
                SELECT id, usuario AS email, nombre, tipo AS rol, activo,
                       '' AS modulos, 0 AS mail_tesoreria, 0 AS mail_petroleo_bitacora,
                       0 AS solo_lectura,
                       COALESCE(fecha_expira, '') AS fecha_expira,
                       COALESCE(invitado_por, '') AS invitado_por
                FROM usuarios
                ORDER BY lower(usuario)
                """
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["modulos_txt"] = "—"
                d["es_operador"] = (d.get("rol") or "") in {"Operador", "Consulta"}
                d["mail_tesoreria"] = False
                d["mail_petroleo_bitacora"] = False
                d["solo_lectura"] = False
                origen, plan = _parse_invitado_meta(d.get("invitado_por"))
                d["invitado_por"] = origen
                d["plan_interes"] = plan
                st = _status_usuario_prueba(d.get("fecha_expira"), plan)
                d.update(st)
                out.append(d)
            return out
        if kind == "demo":
            rows = conn.execute(
                """
                SELECT id, email, rol, modulos, mail_tesoreria,
                       fecha_expira, invitado_por
                FROM usuarios
                ORDER BY lower(email)
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, email, rol, modulos, mail_tesoreria,
                       solo_lectura, mail_petroleo_bitacora
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
        origen, plan = _parse_invitado_meta(d.get("invitado_por"))
        d["invitado_por"] = origen
        d["plan_interes"] = plan
        st = _status_usuario_prueba(d.get("fecha_expira"), plan)
        d.update(st)
        out.append(d)
    return out


def _ensure_demo_web_path() -> None:
    root = (DEMO_WEB_ROOT or "").strip()
    if root and root not in sys.path and os.path.isdir(root):
        sys.path.insert(0, root)


def _ensure_demo_web_runtime() -> None:
    """Prepara path + mock Streamlit + site-packages de demo-web para enviar mails.

    erp-master corre en un venv mínimo (sin streamlit/pandas). Las invitaciones
    importan app_concepcion/app_demo, que requieren esos deps; se reutiliza el
    mock de demo-web y sus site-packages.
    """
    _ensure_demo_web_path()
    root = (DEMO_WEB_ROOT or "").strip() or "/root/demo-web"
    # site-packages del venv agrícola (pandas, etc.)
    for cand in (
        os.path.join(root, ".venv", "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages"),
        os.path.join(root, ".venv", "lib", "python3.10", "site-packages"),
        os.path.join(root, ".venv", "lib", "python3.12", "site-packages"),
    ):
        if os.path.isdir(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
    # Módulos legacy (p.ej. soporte_pelao) viven en /root/demo; al final del path
    # para no tapar app_demo de demo-web.
    for legacy in (
        os.environ.get("ERP_DEMO_LEGACY_ROOT", "").strip(),
        "/root/demo",
        os.path.join(os.path.dirname(root.rstrip("/")), "demo"),
    ):
        if legacy and os.path.isdir(legacy) and legacy not in sys.path:
            sys.path.append(legacy)
    try:
        from demo_web.services.streamlit_mock import (  # noqa: WPS433
            install_streamlit_mock,
            set_secrets_path,
        )

        install_streamlit_mock()
        secrets = (
            os.environ.get("ERP_DEMO_SECRETS")
            or os.environ.get("ERP_SECRETS")
            or "/root/demo/.streamlit/secrets.toml"
        )
        if secrets and os.path.isfile(secrets):
            set_secrets_path(secrets)
    except Exception:
        # Si el mock no carga, el import de app_* fallará con mensaje claro.
        pass


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
    mail_tesoreria: bool = False,
    mail_petroleo: bool = False,
    solo_lectura: bool = False,
) -> tuple[bool, str]:
    email_n = (email or "").strip().lower()
    if not email_n or not _EMAIL_RE.match(email_n):
        return False, "Correo inválido."
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    if rol not in roles_for(kind):
        return False, "Rol no válido para este ERP."
    exp = ""
    user_id = 0
    with tenant_conn(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM usuarios WHERE lower(email) = ?", (email_n,)
        ).fetchone()
        if exists:
            return False, "Ya existe un usuario con ese correo."
        pwd = hash_password(password, kind)
        if kind == "demo":
            exp = (hoy_chile() + timedelta(days=max(1, int(dias_demo)))).isoformat()
            cur = conn.execute(
                """
                INSERT INTO usuarios
                  (email, password, rol, fecha_expira, invitado_por, modulos)
                VALUES (?, ?, ?, ?, ?, '')
                """,
                (email_n, pwd, rol, exp, (invitado_por or "").strip()),
            )
            user_id = int(cur.lastrowid or 0)
        else:
            cur = conn.execute(
                """
                INSERT INTO usuarios (email, password, rol, modulos)
                VALUES (?, ?, ?, '')
                """,
                (email_n, pwd, rol),
            )
            user_id = int(cur.lastrowid or 0)

    if user_id:
        set_mail_flags(
            db_path,
            kind,
            user_id,
            mail_tesoreria=mail_tesoreria,
            mail_petroleo=mail_petroleo if kind == "lc" else None,
            solo_lectura=solo_lectura if kind == "lc" else None,
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
    elif enviar_invitacion:
        ok_mail, mail_txt = send_lc_invitation(
            db_path, email_n, password, rol, invitado_por or ""
        )
        msg = f"{msg} {mail_txt}"
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
        _ensure_demo_web_runtime()
        import app_demo as demo  # noqa: WPS433
        try:
            from demo_web.services.streamlit_mock import set_secrets_path  # noqa: WPS433
            secrets = (
                os.environ.get("ERP_DEMO_SECRETS")
                or "/root/demo/.streamlit/secrets.toml"
            )
            if secrets:
                set_secrets_path(secrets)
        except Exception:
            pass

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


def send_lc_invitation(
    db_path: str,
    email: str,
    password_plain: str,
    rol: str,
    admin_email: str,
) -> tuple[bool, str]:
    """Envía correo de invitación La Concepción."""
    try:
        _ensure_demo_web_runtime()
        import app_concepcion as lc  # noqa: WPS433

        lc.NOMBRE_DB = db_path
        lc.PROD_URL = DEMO_LOGIN_URL
        ok = bool(
            lc.enviar_correo_invitacion_concepcion(
                email, password_plain, rol, admin_email
            )
        )
        if ok:
            return True, f"Correo de invitación enviado a {email}."
        return False, "No se pudo enviar el correo de invitación LC (revise SMTP)."
    except Exception as exc:
        return False, f"Invitación LC no enviada: {exc}"


def reenviar_invitacion(
    db_path: str,
    kind: str,
    user_id: int,
    password_plain: str,
    admin_email: str = "",
) -> tuple[bool, str]:
    """Reenvía invitación (requiere clave en claro para incluirla en el correo)."""
    if not password_plain or len(password_plain) < 4:
        return False, "Indique la clave actual o una nueva (mín. 4) para reenviar."
    with tenant_conn(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        select_cols = ["email", "rol"]
        if "fecha_expira" in cols:
            select_cols.append("fecha_expira")
        row = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM usuarios WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        # Actualiza clave al reenviar para que el correo sea usable.
        conn.execute(
            "UPDATE usuarios SET password = ? WHERE id = ?",
            (hash_password(password_plain, kind), user_id),
        )
    email = row["email"]
    rol = row["rol"]
    if kind == "demo":
        exp = ""
        if "fecha_expira" in row.keys():
            exp = str(row["fecha_expira"] or "")[:10]
        if not exp:
            exp = (hoy_chile() + timedelta(days=DEMO_DIAS_PRUEBA_DEFAULT)).isoformat()
        return send_demo_invitation(
            db_path, email, password_plain, rol, admin_email, exp
        )
    return send_lc_invitation(db_path, email, password_plain, rol, admin_email)


def _load_app_demo_module():
    """Carga app_demo desde DEMO_WEB_ROOT (evita sombra de /root/app_demo.py)."""
    import importlib
    import importlib.util

    _ensure_demo_web_runtime()
    root = (DEMO_WEB_ROOT or "").strip() or "/root/demo-web"
    target = os.path.join(root, "app_demo.py")
    if os.path.isfile(target):
        # Si ya hay un app_demo cargado desde otra ruta, forzar el de demo-web.
        existing = sys.modules.get("app_demo")
        if existing is not None and os.path.abspath(getattr(existing, "__file__", "") or "") != os.path.abspath(target):
            del sys.modules["app_demo"]
        spec = importlib.util.spec_from_file_location("app_demo", target)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["app_demo"] = mod
            spec.loader.exec_module(mod)
            return mod
    import app_demo as demo  # noqa: WPS433

    return demo


def send_demo_extension_notice(
    db_path: str,
    email: str,
    rol: str,
    admin_email: str,
    fecha_expira: str,
    dias_agregados: int,
    fecha_anterior: str = "",
) -> tuple[bool, str]:
    """Envía aviso de extensión al usuario y copia al correo_receptor (mail respaldo)."""
    try:
        demo = _load_app_demo_module()
        try:
            from demo_web.services.streamlit_mock import set_secrets_path  # noqa: WPS433

            secrets = (
                os.environ.get("ERP_DEMO_SECRETS")
                or "/root/demo/.streamlit/secrets.toml"
            )
            if secrets:
                set_secrets_path(secrets)
        except Exception:
            pass

        demo.NOMBRE_DB = db_path
        demo.DEMO_URL = DEMO_LOGIN_URL
        send_fn = getattr(demo, "enviar_correo_extension_prueba_demo", None)
        if not callable(send_fn):
            return False, "Aviso no enviado: falta función de correo de extensión en DEMO."
        res = send_fn(
            email,
            rol,
            admin_email,
            fecha_expira,
            dias_agregados,
            fecha_anterior or "",
        )
        ok_u = bool(res.get("usuario")) if isinstance(res, dict) else bool(res)
        ok_c = bool(res.get("copia", True)) if isinstance(res, dict) else True
        if ok_u and ok_c:
            return True, f"Aviso enviado a {email} (con copia de respaldo)."
        if ok_u and not ok_c:
            return True, f"Aviso enviado a {email}, pero falló la copia de respaldo."
        if (not ok_u) and ok_c:
            return False, "Falló el envío al usuario; se envió la copia de respaldo."
        return False, "No se pudo enviar el aviso de extensión (revise SMTP)."
    except Exception as exc:
        return False, f"Aviso de extensión no enviado: {exc}"


def extender_prueba(
    db_path: str,
    kind: str,
    user_id: int,
    dias: int = 30,
    admin_email: str = "",
    enviar_aviso: bool = True,
) -> tuple[bool, str]:
    """Suma días al plazo de prueba de un usuario DEMO Agrícola.

    Si la fecha actual aún está vigente, suma desde esa fecha.
    Si ya venció o no hay fecha, suma desde hoy.
    Por defecto envía correo al usuario y copia al mail de respaldo (correo_receptor).
    """
    if kind != "demo":
        return False, "Extender prueba solo aplica al DEMO Agrícola."
    try:
        d = int(dias or DEMO_DIAS_PRUEBA_DEFAULT)
    except (TypeError, ValueError):
        d = DEMO_DIAS_PRUEBA_DEFAULT
    d = max(1, min(365, d))
    with tenant_conn(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "fecha_expira" not in cols:
            conn.execute("ALTER TABLE usuarios ADD COLUMN fecha_expira TEXT")
            cols.add("fecha_expira")
        for col, decl in (
            ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
            ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {decl}")
                cols.add(col)
        row = conn.execute(
            """SELECT email, COALESCE(rol, '') AS rol,
                      COALESCE(fecha_expira, '') AS fecha_expira
               FROM usuarios WHERE id = ?""",
            (int(user_id),),
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        email = str(row["email"] or "")
        rol = str(row["rol"] or "operador")
        hoy = hoy_chile()
        base = hoy
        raw = str(row["fecha_expira"] or "").strip()[:10]
        if raw:
            try:
                exp_actual = date.fromisoformat(raw)
                if exp_actual >= hoy:
                    base = exp_actual
            except ValueError:
                pass
        nueva = (base + timedelta(days=d)).isoformat()
        sets = ["fecha_expira = ?"]
        params: list[Any] = [nueva]
        if "alerta_24h_enviada" in cols:
            sets.append("alerta_24h_enviada = 0")
        if "alerta_vencido_enviada" in cols:
            sets.append("alerta_vencido_enviada = 0")
        params.append(int(user_id))
        conn.execute(
            f"UPDATE usuarios SET {', '.join(sets)} WHERE id = ?",
            params,
        )
    prev = raw or "sin fecha"
    msg = (
        f"Prueba de {email} extendida {d} día{'s' if d != 1 else ''} "
        f"(era {prev} → hasta {nueva})."
    )
    if enviar_aviso:
        ok_mail, mail_txt = send_demo_extension_notice(
            db_path,
            email,
            rol,
            admin_email or "",
            nueva,
            d,
            fecha_anterior=raw,
        )
        msg = f"{msg} {mail_txt}"
        if not ok_mail:
            # La extensión ya quedó guardada; avisamos el fallo de correo.
            return True, msg
    return True, msg


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
                "invitado_por": _parse_invitado_meta(r["invitado_por"])[0],
                "plan_interes": _parse_invitado_meta(r["invitado_por"])[1],
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



def reseed_comercial_demo(db_path: str) -> tuple[bool, str]:
    """Re-siembra datos ficticios del DEMO Comercial (no borra usuarios ni empresa)."""
    try:
        import sys

        root = os.environ.get("COMERCIAL_WEB_ROOT", "/root/riomaipo").strip() or "/root/riomaipo"
        if root not in sys.path:
            sys.path.insert(0, root)
        from rmweb.seed_demo import SEED_MARK, sembrar_datos_demo  # noqa: WPS433

        stats = sembrar_datos_demo(db_path)
        return (
            True,
            "Datos DEMO Comercial re-sembrados: "
            f"{stats.get('clientes', 0)} clientes, "
            f"{stats.get('cotizaciones', 0)} cotizaciones, "
            f"{stats.get('cuentas', 0)} CxC, "
            f"{stats.get('abonos', 0)} abonos "
            f"({stats.get('mark') or SEED_MARK}).",
        )
    except Exception as exc:
        return False, f"No se pudo re-sembrar Comercial DEMO: {exc}"


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
    solo_lectura: bool | None = None,
) -> tuple[bool, str]:
    with tenant_conn(db_path) as conn:
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



def _import_erp_respaldo():
    """Carga /root/erp_respaldo.py (no la copia de demo-web en PYTHONPATH)."""
    import importlib.util
    import sys

    path = "/root/erp_respaldo.py"
    # Reusar si ya está cargado desde esa ruta
    mod = sys.modules.get("erp_respaldo_root")
    if mod is not None and getattr(mod, "__file__", None) == path:
        return mod
    spec = importlib.util.spec_from_file_location("erp_respaldo_root", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["erp_respaldo_root"] = mod
    spec.loader.exec_module(mod)
    return mod



# Rubros con respaldo de código compartido (1 zip por producto).
RUBROS_RESPALDO_CODIGO = ("agricola", "comercial", "constructora")

# Tenant canonico donde se edita el checkbox de CODIGO por rubro.
RESPALDO_CODIGO_OWNER_POR_RUBRO = {
    "agricola": "concepcion",
    "comercial": "riomaipo",
    "constructora": "constructora-demo",
}
RESPALDO_CODIGO_OWNER_LABEL = {
    "concepcion": "La Concepción",
    "riomaipo": "Río Maipo",
    "constructora-demo": "DEMO Constructora",
}


def rubro_codigo_owner_slug(producto: str) -> str:
    return RESPALDO_CODIGO_OWNER_POR_RUBRO.get((producto or "").strip().lower(), "")


def es_owner_codigo_rubro(slug: str, producto: str) -> bool:
    owner = rubro_codigo_owner_slug(producto)
    return bool(owner) and (slug or "").strip().lower() == owner


def label_owner_codigo_rubro(producto: str) -> str:
    owner = rubro_codigo_owner_slug(producto)
    return RESPALDO_CODIGO_OWNER_LABEL.get(owner, owner or "—")


def get_respaldo_config(db_path: str, producto: str = "") -> dict[str, str]:
    """Datos = por tenant. Codigo activo/freq/ultimo = por rubro (producto)."""
    with tenant_conn(db_path) as conn:
        cfg = {
            "email": _meta_get(conn, "respaldo_email"),
            "activo": _meta_get(conn, "respaldo_activo", "0"),  # datos (compat)
            "activo_datos": _meta_get(conn, "respaldo_activo", "0"),
            "frecuencia": _meta_get(conn, "respaldo_frecuencia", "diario"),
            "codigo_frecuencia": _meta_get(
                conn, "respaldo_codigo_frecuencia", "semanal"
            ),
            "ultimo_envio": _meta_get(conn, "respaldo_ultimo_envio"),
            "ultimo_error": _meta_get(conn, "respaldo_ultimo_error"),
            "codigo_ultimo_envio": _meta_get(conn, "respaldo_codigo_ultimo_envio"),
            "codigo_ultimo_error": _meta_get(conn, "respaldo_codigo_ultimo_error"),
            "activo_codigo": "0",
        }
    rubro = (producto or "").strip().lower()
    if rubro in RUBROS_RESPALDO_CODIGO:
        try:
            _ensure_demo_web_path()
            erp_r = _import_erp_respaldo()
            meta = erp_r.load_codigo_rubro_meta(rubro)
            cfg["activo_codigo"] = "1" if meta.get("activo") else "0"
            if meta.get("frecuencia"):
                cfg["codigo_frecuencia"] = str(meta.get("frecuencia"))
            if meta.get("ultimo_envio"):
                cfg["codigo_ultimo_envio"] = str(meta.get("ultimo_envio"))
            if meta.get("ultimo_error"):
                cfg["codigo_ultimo_error"] = str(meta.get("ultimo_error"))
            # email del rubro si el tenant no tiene
            if not (cfg.get("email") or "").strip() and meta.get("email"):
                cfg["email"] = str(meta.get("email"))
        except Exception:
            pass
    return cfg


def save_respaldo_config(
    db_path: str,
    email: str,
    activo: bool,
    freq_datos: str,
    freq_codigo: str,
    *,
    activo_datos: bool | None = None,
    activo_codigo: bool | None = None,
    producto: str = "",
    guardar_codigo: bool = False,
    slug: str = "",
) -> tuple[bool, str]:
    """Guarda datos (tenant). Codigo del rubro solo si guardar_codigo y es owner."""
    email_n = (email or "").strip()
    if freq_datos not in FRECUENCIAS:
        freq_datos = "diario"
    if freq_codigo not in FRECUENCIAS:
        freq_codigo = "semanal"
    if activo_datos is None:
        activo_datos = bool(activo)
    if activo_codigo is None:
        activo_codigo = bool(activo)

    rubro = (producto or "").strip().lower()
    if guardar_codigo:
        if not es_owner_codigo_rubro(slug, rubro):
            return False, (
                "El respaldo de código se configura solo en "
                f"{label_owner_codigo_rubro(rubro)}."
            )
    else:
        # Tenants no-owner: no tocar JSON de codigo ni exigir email por codigo
        activo_codigo = False

    needs_email = bool(activo_datos) or (bool(guardar_codigo) and bool(activo_codigo))
    if needs_email:
        parts = [p.strip() for p in email_n.replace(";", ",").split(",") if p.strip()]
        if not parts or not all(_EMAIL_RE.match(p) for p in parts):
            return False, "Correo destino inválido para activar el respaldo."
    with tenant_conn(db_path) as conn:
        _meta_set(conn, "respaldo_email", email_n)
        _meta_set(conn, "respaldo_activo", "1" if activo_datos else "0")
        _meta_set(conn, "respaldo_frecuencia", freq_datos)
        _meta_set(conn, "respaldo_codigo_frecuencia", freq_codigo)

    if guardar_codigo and rubro in RUBROS_RESPALDO_CODIGO:
        try:
            _ensure_demo_web_path()
            erp_r = _import_erp_respaldo()
            erp_r.save_codigo_rubro_meta(
                rubro,
                {
                    "activo": bool(activo_codigo),
                    "frecuencia": freq_codigo,
                    "email": email_n,
                },
            )
        except Exception as exc:
            return False, f"Datos guardados, pero falló código del rubro: {exc}"
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


# Defaults de CC prorrateables (sin importar app_demo/app_concepcion: Master no tiene Streamlit).
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
        "directos": ["EL ESPINO", "OTROS"],
    },
}


def _prorrateo_meta(kind: str) -> dict[str, Any]:
    return dict(_PRORRATEO_DEFAULTS.get(kind) or _PRORRATEO_DEFAULTS["demo"])


def _ensure_prorrateo_table(conn) -> None:
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
            conn.execute("ALTER TABLE prorrateo_cc ADD COLUMN superficie_ha REAL DEFAULT 0")
        except Exception:
            pass


def get_prorrateo_cc(db_path: str, kind: str) -> dict[str, Any]:
    """% de prorrateo por CC (solo porcentajes, ingreso manual)."""
    meta = _prorrateo_meta(kind)
    cuarteles = list(meta["cuarteles"])
    default = dict(meta.get("default_pct") or {})
    with tenant_conn(db_path) as conn:
        _ensure_prorrateo_table(conn)
        rows = conn.execute(
            "SELECT centro_costo, porcentaje FROM prorrateo_cc ORDER BY centro_costo"
        ).fetchall()
        pcts = {str(r[0]): float(r[1]) for r in rows} if rows else dict(default)
        # Si hay filas en DB que no están en la lista fija, incluirlas (orden alfabético al final).
        extras = [cc for cc in pcts if cc not in cuarteles]
        if extras:
            cuarteles = cuarteles + sorted(extras)
    rows_out = []
    for cc in cuarteles:
        rows_out.append(
            {
                "cc": cc,
                "nombre": str(cc).title() if str(cc).isupper() else str(cc),
                "porcentaje": float(pcts.get(cc, default.get(cc, 0)) or 0),
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
    db_path: str, kind: str, porcentajes: dict[str, float]
) -> tuple[bool, str]:
    """Guarda % manuales (deben sumar 100). Conserva superficie_ha si existe."""
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

        for cc, pct in vals.items():
            if has_ha:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje, superficie_ha) VALUES (?,?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct), float(ha_map.get(cc, 0))),
                )
            else:
                conn.execute(
                    "INSERT INTO prorrateo_cc (centro_costo, porcentaje) VALUES (?,?) "
                    "ON CONFLICT(centro_costo) DO UPDATE SET porcentaje=excluded.porcentaje",
                    (cc, float(pct)),
                )
    detalle = ", ".join(f"{k}={v:.2f}%" for k, v in vals.items())
    return True, f"Prorrateo CC guardado ({detalle})."



def _comercial_hash(password: str) -> tuple[str, str]:
    """PBKDF2 compatible con rmweb.core.hash_password."""
    import hashlib
    import secrets as _secrets

    salt = _secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return salt, digest


def create_user_comercial(
    db_path: str,
    email: str,
    password: str,
    rol: str,
    nombre: str = "",
    *,
    es_demo: bool = False,
    dias_demo: int = 30,
    invitado_por: str = "",
    enviar_invitacion: bool = False,
    secrets_path: str = "",
) -> tuple[bool, str]:
    email_n = (email or "").strip().lower()
    if not email_n or "@" not in email_n:
        return False, "Correo inválido."
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    if rol not in ROLES_COMERCIAL:
        return False, "Rol no válido."
    salt, digest = _comercial_hash(password)
    exp = None
    if es_demo:
        try:
            d = max(1, int(dias_demo or 30))
        except (TypeError, ValueError):
            d = 30
        exp = (hoy_chile() + timedelta(days=d)).isoformat()
    with tenant_conn(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        for col, decl in (
            ("fecha_expira", "TEXT"),
            ("invitado_por", "TEXT"),
            ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
            ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {decl}")
        exists = conn.execute(
            "SELECT id FROM usuarios WHERE lower(usuario)=?", (email_n,)
        ).fetchone()
        if exists:
            return False, "Ya existe ese usuario."
        conn.execute(
            """INSERT INTO usuarios
               (usuario, salt, clave_hash, nombre, tipo, activo,
                fecha_expira, invitado_por, alerta_24h_enviada, alerta_vencido_enviada)
               VALUES (?,?,?,?,?,1,?,?,0,0)""",
            (
                email_n,
                salt,
                digest,
                (nombre or "").strip() or email_n,
                rol,
                exp,
                (invitado_por or "").strip() if es_demo else "",
            ),
        )
    msg = f"Usuario {email_n} creado."
    if es_demo and exp:
        msg += f" Vigencia hasta {exp}."
    if es_demo and enviar_invitacion:
        try:
            import sys

            root = os.environ.get("COMERCIAL_WEB_ROOT", "/root/riomaipo").strip() or "/root/riomaipo"
            if root not in sys.path:
                sys.path.insert(0, root)
            from rmweb.demo_invitacion import (  # noqa: WPS433
                DEMO_DIAS_PRUEBA,
                enviar_correo_invitacion_demo,
            )

            ok_mail, mail_txt = enviar_correo_invitacion_demo(
                secrets_path=secrets_path or "",
                email=email_n,
                password_plain=password,
                rol=rol,
                admin_email=invitado_por or "",
                fecha_expira=exp or "",
                dias=int(dias_demo or DEMO_DIAS_PRUEBA),
            )
            msg = f"{msg} {mail_txt}"
            if not ok_mail:
                return True, msg
        except Exception as exc:
            msg = f"{msg} Invitación no enviada: {exc}"
    return True, msg


def reenviar_invitacion_comercial(
    db_path: str,
    user_id: int,
    password_plain: str,
    admin_email: str,
    secrets_path: str = "",
    dias_demo: int = 30,
) -> tuple[bool, str]:
    """Reenvía mail de invitación DEMO Comercial (requiere clave en claro)."""
    if not password_plain or len(password_plain) < 4:
        return False, "Indique la clave (mín. 4) para incluirla en el correo."
    with tenant_conn(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        for col, decl in (
            ("fecha_expira", "TEXT"),
            ("invitado_por", "TEXT"),
            ("alerta_24h_enviada", "INTEGER DEFAULT 0"),
            ("alerta_vencido_enviada", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {decl}")
        row = conn.execute(
            "SELECT usuario, tipo, fecha_expira FROM usuarios WHERE id=?",
            (int(user_id),),
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        email_n = row[0]
        rol = row[1] or "Operador"
        exp = str(row[2] or "")[:10]
        if not exp:
            try:
                d = max(1, int(dias_demo or 30))
            except (TypeError, ValueError):
                d = 30
            exp = (hoy_chile() + timedelta(days=d)).isoformat()
            conn.execute(
                """UPDATE usuarios
                   SET fecha_expira=?, invitado_por=?,
                       alerta_24h_enviada=0, alerta_vencido_enviada=0
                   WHERE id=?""",
                (exp, (admin_email or "").strip(), int(user_id)),
            )
        # actualizar clave al reenviar (igual que útil para el invitado)
        salt, digest = _comercial_hash(password_plain)
        conn.execute(
            "UPDATE usuarios SET salt=?, clave_hash=? WHERE id=?",
            (salt, digest, int(user_id)),
        )
    try:
        import sys

        root = os.environ.get("COMERCIAL_WEB_ROOT", "/root/riomaipo").strip() or "/root/riomaipo"
        if root not in sys.path:
            sys.path.insert(0, root)
        from rmweb.demo_invitacion import (  # noqa: WPS433
            DEMO_DIAS_PRUEBA,
            enviar_correo_invitacion_demo,
        )

        return enviar_correo_invitacion_demo(
            secrets_path=secrets_path or "",
            email=email_n,
            password_plain=password_plain,
            rol=rol,
            admin_email=admin_email or "",
            fecha_expira=exp,
            dias=int(dias_demo or DEMO_DIAS_PRUEBA),
        )
    except Exception as exc:
        return False, f"No se pudo reenviar invitación: {exc}"


def change_password_comercial(db_path: str, user_id: int, password: str) -> tuple[bool, str]:
    if not password or len(password) < 4:
        return False, "La clave debe tener al menos 4 caracteres."
    salt, digest = _comercial_hash(password)
    with tenant_conn(db_path) as conn:
        cur = conn.execute(
            "UPDATE usuarios SET salt=?, clave_hash=? WHERE id=?",
            (salt, digest, int(user_id)),
        )
        if cur.rowcount == 0:
            return False, "Usuario no encontrado."
    return True, "Clave actualizada."


def change_role_comercial(db_path: str, user_id: int, rol: str) -> tuple[bool, str]:
    if rol not in ROLES_COMERCIAL:
        return False, "Rol no válido."
    with tenant_conn(db_path) as conn:
        row = conn.execute("SELECT tipo FROM usuarios WHERE id=?", (int(user_id),)).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        if row[0] == protected_role("comercial") and rol != protected_role("comercial"):
            n = conn.execute(
                "SELECT COUNT(*) FROM usuarios WHERE tipo=? AND activo=1",
                (protected_role("comercial"),),
            ).fetchone()[0]
            if int(n or 0) <= 1:
                return False, "No se puede quitar el último Administrador."
        conn.execute("UPDATE usuarios SET tipo=? WHERE id=?", (rol, int(user_id)))
    return True, "Rol actualizado."


def delete_user_comercial(db_path: str, user_id: int) -> tuple[bool, str]:
    with tenant_conn(db_path) as conn:
        row = conn.execute(
            "SELECT tipo, usuario FROM usuarios WHERE id=?", (int(user_id),)
        ).fetchone()
        if not row:
            return False, "Usuario no encontrado."
        if row[0] == protected_role("comercial"):
            n = conn.execute(
                "SELECT COUNT(*) FROM usuarios WHERE tipo=? AND activo=1",
                (protected_role("comercial"),),
            ).fetchone()[0]
            if int(n or 0) <= 1:
                return False, "No se puede eliminar el último Administrador."
        conn.execute("DELETE FROM usuarios WHERE id=?", (int(user_id),))
    return True, f"Usuario {row[1]} eliminado."


def get_mail_alertas(secrets_path: str) -> dict[str, str]:
    """Receptor y flags de alertas (gmail_smtp + toggles acceso/pago)."""
    path = (secrets_path or "").strip()
    out = {
        "correo_receptor": "",
        "correo_emisor": "",
        "secrets_path": path,
        "ok": "0",
        "alerta_acceso": "1",
        "alerta_pago": "0",
    }
    if not path or not os.path.isfile(path):
        return out
    try:
        _ensure_demo_web_path()
        from erp_respaldo import _cargar_toml  # noqa: WPS433

        conf = (_cargar_toml(path) or {}).get("gmail_smtp") or {}
        out["correo_receptor"] = str(conf.get("correo_receptor") or "").strip()
        out["correo_emisor"] = str(conf.get("correo_emisor") or "").strip()
        # Defaults: acceso ON si no está definido; pago OFF salvo que exista clave=1
        if "alerta_acceso" in conf:
            out["alerta_acceso"] = "1" if str(conf.get("alerta_acceso")).strip() in {"1", "true", "True", "yes", "on"} else "0"
        else:
            out["alerta_acceso"] = "1"
        if "alerta_pago" in conf:
            out["alerta_pago"] = "1" if str(conf.get("alerta_pago")).strip() in {"1", "true", "True", "yes", "on"} else "0"
        else:
            out["alerta_pago"] = "0"
        out["ok"] = "1"
    except Exception:
        pass
    return out


def save_mail_alertas(
    secrets_path: str,
    correo_receptor: str,
    *,
    alerta_acceso: bool | None = None,
    alerta_pago: bool | None = None,
) -> tuple[bool, str]:
    """Actualiza receptor y, opcionalmente, flags de alerta acceso/pago en secrets."""
    path = (secrets_path or "").strip()
    email_n = (correo_receptor or "").strip()
    parts = [p.strip() for p in email_n.replace(";", ",").split(",") if p.strip()]
    if not parts or not all(_EMAIL_RE.match(p) for p in parts):
        return False, "Correo receptor de alertas inválido."
    if not path or not os.path.isfile(path):
        return False, f"No se encontró secrets del tenant: {path or '—'}"
    try:
        texto = open(path, encoding="utf-8").read()
    except OSError as exc:
        return False, f"No se pudo leer secrets: {exc}"

    valor = parts[0] if len(parts) == 1 else ", ".join(parts)

    def _upsert(texto_in: str, clave: str, valor_line: str) -> str:
        if re.search(rf"(?m)^\s*{re.escape(clave)}\s*=", texto_in):
            return re.sub(
                rf"(?m)^\s*{re.escape(clave)}\s*=\s*.*$",
                valor_line,
                texto_in,
                count=1,
            )
        m_sec = re.search(r"(?mi)^(\s*\[gmail_smtp\]\s*\n)", texto_in)
        if m_sec:
            return texto_in[: m_sec.end()] + valor_line + "\n" + texto_in[m_sec.end() :]
        return texto_in.rstrip() + "\n\n[gmail_smtp]\n" + valor_line + "\n"

    texto2 = _upsert(texto, "correo_receptor", f'correo_receptor = "{valor}"')
    if alerta_acceso is not None:
        flag = "1" if alerta_acceso else "0"
        texto2 = _upsert(texto2, "alerta_acceso", f'alerta_acceso = "{flag}"')
    if alerta_pago is not None:
        flag = "1" if alerta_pago else "0"
        texto2 = _upsert(texto2, "alerta_pago", f'alerta_pago = "{flag}"')

    bak = path + ".bak-master"
    try:
        if not os.path.exists(bak):
            with open(bak, "w", encoding="utf-8") as f:
                f.write(texto)
        with open(path, "w", encoding="utf-8") as f:
            f.write(texto2)
    except OSError as exc:
        return False, f"No se pudo guardar secrets: {exc}"
    extras = []
    if alerta_acceso is not None:
        extras.append("acceso=" + ("ON" if alerta_acceso else "OFF"))
    if alerta_pago is not None:
        extras.append("pago=" + ("ON" if alerta_pago else "OFF"))
    detalle = valor + ((" · " + ", ".join(extras)) if extras else "")
    return True, f"Mail de alertas actualizado: {detalle}"


def enviar_respaldo_ahora(
    tenant: dict[str, Any],
    *,
    tipo: str = "datos",
    usuario: str = "MASTER",
) -> tuple[bool, str]:
    """Ejecuta envío inmediato de respaldo datos (tenant) o código (rubro)."""
    _ensure_demo_web_path()
    try:
        erp_r = _import_erp_respaldo()
        ejecutar_respaldo = erp_r.ejecutar_respaldo
        ejecutar_respaldo_codigo_rubro = erp_r.ejecutar_respaldo_codigo_rubro
        load_codigo_rubro_meta = erp_r.load_codigo_rubro_meta
    except Exception as exc:
        return False, f"Módulo respaldo no disponible: {exc}"

    db = tenant.get("db") or ""
    secrets = tenant.get("secrets") or ""
    nombre = tenant.get("nombre_erp") or tenant.get("nombre") or "ERP"
    producto = (tenant.get("producto") or "").strip().lower()
    if not db or not os.path.isfile(db):
        return False, "Base de datos del tenant no encontrada."
    try:
        if tipo == "codigo":
            rubro = producto if producto in RUBROS_RESPALDO_CODIGO else ""
            if not rubro:
                return False, "Este cliente no tiene rubro para respaldo de código."
            email = ""
            with tenant_conn(db) as conn:
                email = _meta_get(conn, "respaldo_email")
            if not email:
                email = (load_codigo_rubro_meta(rubro).get("email") or "")
            res = ejecutar_respaldo_codigo_rubro(
                rubro,
                forzar=True,
                usuario=usuario or "MASTER",
                email_override=email or None,
            )
            if res.get("ok"):
                return True, f"Respaldo de código ({rubro}) enviado."
            return False, (
                f"No se pudo enviar respaldo de código: "
                f"{res.get('motivo') or ''} {res.get('error') or ''}"
            ).strip()
        with tenant_conn(db) as conn:
            ok = ejecutar_respaldo(
                conn,
                nombre,
                os.path.abspath(db),
                secrets,
                forzar=True,
                usuario=usuario or "MASTER",
            )
            return (
                bool(ok),
                "Respaldo de datos enviado." if ok else "No se pudo enviar respaldo de datos.",
            )
    except Exception as exc:
        return False, f"Error al enviar respaldo: {exc}"


def crear_descarga_db(db_path: str) -> tuple[bool, str, str | None]:
    """Genera .db.gz temporal para descarga. Retorna (ok, msg, path)."""
    _ensure_demo_web_path()
    if not db_path or not os.path.isfile(db_path):
        return False, "Base de datos no encontrada.", None
    try:
        from erp_respaldo import crear_archivo_respaldo  # noqa: WPS433

        path = crear_archivo_respaldo(db_path)
        if path and os.path.isfile(path):
            return True, "Archivo listo.", path
        return False, "No se pudo comprimir la base.", None
    except Exception as exc:
        return False, f"No se pudo preparar descarga: {exc}", None


def _smtp_html_sender(secrets_path: str):
    """Callable compatible con erp_soporte: (asunto, html, destinatarios) -> bool."""
    _ensure_demo_web_path()
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import smtplib

    from erp_respaldo import cargar_smtp  # noqa: WPS433

    smtp = cargar_smtp(secrets_path or "")
    if not smtp:
        return None

    def _send(asunto: str, html: str, destinatarios) -> bool:
        dests = [d.strip() for d in (destinatarios or []) if str(d or "").strip()]
        if not dests:
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = asunto
            msg["From"] = smtp["from_header"]
            msg["To"] = ", ".join(dests)
            msg.attach(MIMEText(html or "", "html", "utf-8"))
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
            server.starttls()
            server.login(smtp["emisor"], smtp["clave"])
            server.sendmail(smtp["emisor"], dests, msg.as_string())
            server.quit()
            return True
        except Exception:
            return False

    return _send


def list_tickets_soporte(
    tenants: list[dict[str, Any]],
    *,
    solo_pendientes: bool = False,
) -> dict[str, Any]:
    """Inbox federado de tickets_soporte de todos los tenants administrables."""
    _ensure_demo_web_path()
    from erp_soporte import (  # noqa: WPS433
        STATUSES_SOPORTE,
        _ticket_esta_finalizado,
        contar_tickets_soporte_no_resueltos,
        migrar_tickets_soporte,
    )

    pendientes: list[dict[str, Any]] = []
    historial: list[dict[str, Any]] = []
    n_pend = 0

    for t in tenants or []:
        db = (t.get("db") or "").strip()
        if not db or not os.path.isfile(db):
            continue
        slug = t.get("slug") or ""
        nombre = t.get("nombre") or slug
        try:
            with tenant_conn(db) as conn:
                migrar_tickets_soporte(conn)
                n_pend += int(contar_tickets_soporte_no_resueltos(conn) or 0)
                rows = conn.execute(
                    """SELECT id, codigo_ticket, usuario, status, fecha_creacion,
                              COALESCE(leido_admin, 0), descripcion,
                              COALESCE(respuesta_admin, ''), fecha_respuesta, erp_origen
                       FROM tickets_soporte
                       ORDER BY COALESCE(leido_admin, 0) ASC, id DESC"""
                ).fetchall()
        except Exception:
            continue

        for r in rows:
            item = {
                "tenant_slug": slug,
                "tenant_nombre": nombre,
                "id": int(r[0]),
                "codigo": r[1] or f"#{r[0]}",
                "usuario": r[2] or "",
                "estado": r[3] or "",
                "fecha": str(r[4] or "")[:19],
                "nuevo": not bool(r[5]),
                "descripcion": r[6] or "",
                "respuesta": r[7] or "",
                "fecha_respuesta": str(r[8] or "")[:19],
                "erp": r[9] or nombre,
            }
            if _ticket_esta_finalizado(item["estado"]):
                if not solo_pendientes:
                    historial.append(item)
            else:
                pendientes.append(item)

    pendientes.sort(key=lambda x: (0 if x["nuevo"] else 1, -(x["id"] or 0)))
    historial.sort(key=lambda x: -(x["id"] or 0))
    return {
        "pendientes": pendientes,
        "historial": historial,
        "n_pendientes": n_pend,
        "statuses": list(STATUSES_SOPORTE),
    }


def marcar_ticket_soporte_leido(tenant: dict[str, Any], ticket_id: int) -> None:
    _ensure_demo_web_path()
    from erp_soporte import marcar_ticket_leido_admin, migrar_tickets_soporte  # noqa: WPS433

    db = (tenant.get("db") or "").strip()
    if not db or not ticket_id:
        return
    with tenant_conn(db) as conn:
        migrar_tickets_soporte(conn)
        marcar_ticket_leido_admin(conn, int(ticket_id))


def responder_ticket_soporte(
    tenant: dict[str, Any],
    ticket_id: int,
    respuesta: str,
    status: str,
) -> tuple[bool, str]:
    """Responde un ticket en el DB del tenant y notifica por correo al usuario."""
    _ensure_demo_web_path()
    from erp_soporte import (  # noqa: WPS433
        STATUSES_SOPORTE,
        _fetch_ticket_soporte,
        enviar_correo_respuesta_ticket,
        migrar_tickets_soporte,
    )

    db = (tenant.get("db") or "").strip()
    if not db or not os.path.isfile(db):
        return False, "Base del cliente no disponible."
    try:
        tid = int(ticket_id)
    except (TypeError, ValueError):
        return False, "Ticket inválido."
    txt = (respuesta or "").strip()
    if len(txt) < 3:
        return False, "Escriba una respuesta de al menos 3 caracteres."
    nuevo_st = (status or "Abierto").strip()
    if nuevo_st not in STATUSES_SOPORTE:
        nuevo_st = "Abierto"

    nombre_erp = tenant.get("nombre_erp") or tenant.get("nombre") or tenant.get("slug") or "ERP"
    with tenant_conn(db) as conn:
        migrar_tickets_soporte(conn)
        row = _fetch_ticket_soporte(conn, tid)
        if not row:
            return False, "Ticket no encontrado."
        usuario, descripcion = row[0], row[1]
        codigo = (row[8] if len(row) > 8 else None) or f"#{tid}"
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo

            f_h = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            f_h = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE tickets_soporte
               SET respuesta_admin=?, fecha_respuesta=?, status=?, fecha_actualizacion=?, leido_admin=1
               WHERE id=?""",
            (txt, f_h, nuevo_st, f_h, tid),
        )

    sender = _smtp_html_sender(tenant.get("secrets") or "")
    mail_ok = False
    if sender:
        mail_ok = bool(
            enviar_correo_respuesta_ticket(
                nombre_erp, codigo, usuario, descripcion, txt, sender
            )
        )
    if mail_ok:
        return True, f"Respuesta enviada a {usuario} · ticket {codigo} ({tenant.get('nombre')})."
    return (
        True,
        f"Respuesta guardada en ticket {codigo} ({tenant.get('nombre')}), "
        "pero no se pudo enviar el correo al usuario.",
    )
