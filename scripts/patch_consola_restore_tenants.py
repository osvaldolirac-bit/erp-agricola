#!/usr/bin/env python3
"""Restaura tenants comercial/constructora y tenant_admin completo en consola VPS."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_guard import require_safe_patch

require_safe_patch(__file__)

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/erp_master/erp_master")
CONFIG = ROOT / "config.py"
TAD = ROOT / "tenant_admin.py"
TAD_EXT = ROOT / "tenant_admin.py.bak_extender_20260805130840"
STAMP = datetime.now().strftime("%Y%m%d%H%M%S")

GLOBALGAP_BLOCK = '''
ROLES_GLOBALGAP = ("admin",)

MENU_GLOBALGAP = [
    ("Panel consultor", "PanelGlobalGAP"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),
    ("Manual", "Manual"),
]
'''

MENU_PATCH_OLD = """def menu_for(kind: str) -> list[tuple[str, str]]:
    if kind == "lc":
        return list(MENU_LC)
    if kind == "comercial":
        return list(MENU_COMERCIAL)
    return list(MENU_DEMO)"""

MENU_PATCH_NEW = """def menu_for(kind: str) -> list[tuple[str, str]]:
    if kind == "globalgap":
        return list(MENU_GLOBALGAP)
    if kind == "lc":
        return list(MENU_LC)
    if kind == "comercial":
        return list(MENU_COMERCIAL)
    return list(MENU_DEMO)"""

ROLES_PATCH_OLD = """def roles_for(kind: str) -> tuple[str, ...]:
    if kind == "lc":
        return ROLES_LC
    if kind == "comercial":
        return ROLES_COMERCIAL
    return ROLES_DEMO"""

ROLES_PATCH_NEW = """def roles_for(kind: str) -> tuple[str, ...]:
    if kind == "globalgap":
        return ROLES_GLOBALGAP
    if kind == "lc":
        return ROLES_LC
    if kind == "comercial":
        return ROLES_COMERCIAL
    return ROLES_DEMO"""

PROT_PATCH_OLD = """def protected_role(kind: str) -> str:
    if kind == "lc":
        return "admin"
    if kind == "comercial":
        return "Administrador"
    return "super_admin"
"""

PROT_PATCH_NEW = """def protected_role(kind: str) -> str:
    if kind == "globalgap":
        return "admin"
    if kind == "lc":
        return "admin"
    if kind == "comercial":
        return "Administrador"
    return "super_admin"
"""

CONFIG_TEXT = '''from __future__ import annotations

import os
import secrets


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


class Config:
    SECRET_KEY = _env("ERP_MASTER_SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env("ERP_MASTER_COOKIE_SECURE", "1") in {"1", "true", "yes"}
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # techo absoluto 12h
    SESSION_IDLE_SECONDS = int(_env("ERP_MASTER_SESSION_IDLE", str(1200)))
    SESSION_IDLE_WARN_SECONDS = int(_env("ERP_MASTER_SESSION_IDLE_WARN", str(120)))

    DATABASE = _env("ERP_MASTER_DB", "/root/erp_master.db")
    BRAND_NAME = "ERP Master"
    BRAND_TAGLINE = "Super consola · Super Admin y Administrador"

    TENANTS = [
        {
            "slug": "concepcion",
            "nombre": "La Concepción",
            "descripcion": "Producción agrícola",
            "producto": "agricola",
            "url": "/agricola/",
            "url_dashboard": "/agricola/m/dashboard",
            "estado": "activo",
        },
        {
            "slug": "demo",
            "nombre": "DEMO Agrícola",
            "descripcion": "Pruebas e invitaciones",
            "producto": "agricola",
            "url": "/agricola/",
            "url_dashboard": "/agricola/m/dashboard",
            "estado": "activo",
        },
        {
            "slug": "globalgap",
            "nombre": "GlobalGAP Consultor",
            "descripcion": "Certificación multi-cliente",
            "producto": "agricola",
            "url": "/agricola/globalgap/",
            "url_dashboard": "/agricola/globalgap/panel",
            "estado": "activo",
        },
        {
            "slug": "riomaipo",
            "nombre": "Río Maipo",
            "descripcion": "Cotizaciones y cobranza · construcción",
            "producto": "comercial",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
            "estado": "activo",
        },
        {
            "slug": "comercial-lc",
            "nombre": "Comercial LC",
            "descripcion": "Cotizaciones y cobranza · agrícola (provisorio)",
            "producto": "comercial",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
            "estado": "activo",
        },
        {
            "slug": "comercial-demo",
            "nombre": "DEMO Comercial",
            "descripcion": "Pruebas e invitaciones · Comercial",
            "producto": "comercial",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
            "estado": "activo",
        },
        {
            "slug": "constructora-demo",
            "nombre": "DEMO Constructora",
            "descripcion": "Pruebas e invitaciones · Constructora",
            "producto": "constructora",
            "url": "/constructora/",
            "url_dashboard": "/constructora/",
            "estado": "activo",
        },
    ]

    ADMIN_TENANTS = [
        {
            "slug": "concepcion",
            "nombre": "La Concepción",
            "kind": "lc",
            "producto": "agricola",
            "db": _env("ERP_LC_DB", "/root/erp_concepcion_v6.db"),
            "secrets": _env(
                "ERP_LC_SECRETS",
                _env("ERP_SECRETS", "/root/.streamlit/secrets.toml"),
            ),
            "nombre_erp": "ERP Agrícola La Concepción",
            "url": "/agricola/",
            "url_admin": "/agricola/m/admin",
        },
        {
            "slug": "demo",
            "nombre": "DEMO Agrícola",
            "kind": "demo",
            "producto": "agricola",
            "db": _env("ERP_DEMO_DB", "/root/demo/erp_demo.db"),
            "secrets": _env("ERP_DEMO_SECRETS", "/root/demo/.streamlit/secrets.toml"),
            "nombre_erp": "ERP DEMO AGRICOLA",
            "url": "/agricola/",
            "url_admin": "/agricola/m/admin",
        },
        {
            "slug": "globalgap",
            "nombre": "GlobalGAP Consultor",
            "kind": "globalgap",
            "producto": "agricola",
            "db": _env("ERP_GLOBALGAP_DB", "/root/globalgap/erp_globalgap.db"),
            "secrets": _env("ERP_GLOBALGAP_SECRETS", "/root/globalgap/.streamlit/secrets.toml"),
            "nombre_erp": "GlobalGAP Consultor",
            "url": "/agricola/globalgap/",
            "url_admin": "/agricola/globalgap/panel",
        },
        {
            "slug": "riomaipo",
            "nombre": "Río Maipo",
            "kind": "comercial",
            "producto": "comercial",
            "db": _env("RIOMAIPO_DB", "/root/riomaipo/data/riomaipo_erp.db"),
            "secrets": _env("RIOMAIPO_SECRETS", "/root/riomaipo/secrets_riomaipo.toml"),
            "nombre_erp": "Río Maipo",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
        },
        {
            "slug": "comercial-lc",
            "nombre": "Comercial LC",
            "kind": "comercial",
            "producto": "comercial",
            "db": _env("COMERCIAL_LC_DB", "/root/riomaipo/data/comercial_lc.db"),
            "secrets": _env(
                "COMERCIAL_LC_SECRETS", "/root/riomaipo/secrets_comercial_lc.toml"
            ),
            "nombre_erp": "Comercial LC",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
        },
        {
            "slug": "comercial-demo",
            "nombre": "DEMO Comercial",
            "kind": "comercial",
            "producto": "comercial",
            "es_demo": True,
            "db": _env("COMERCIAL_DEMO_DB", "/root/riomaipo/data/comercial_demo.db"),
            "secrets": _env(
                "COMERCIAL_DEMO_SECRETS", "/root/riomaipo/secrets_comercial_demo.toml"
            ),
            "nombre_erp": "DEMO Comercial",
            "url": "/comercial/",
            "url_dashboard": "/comercial/",
        },
        {
            "slug": "constructora-demo",
            "nombre": "DEMO Constructora",
            "kind": "comercial",
            "producto": "constructora",
            "es_demo": True,
            "db": _env("CONSTRUCTORA_DEMO_DB", "/root/constructora/data/constructora_demo.db"),
            "secrets": _env(
                "CONSTRUCTORA_DEMO_SECRETS",
                "/root/constructora/secrets_constructora_demo.toml",
            ),
            "nombre_erp": "DEMO Constructora",
            "url": "/constructora/",
            "url_dashboard": "/constructora/",
        },
    ]

    STATUS_DIR = _env("ERP_STATUS_DIR", "/root/erp_status")
    BRIDGE_SECRET = _env("ERP_MASTER_BRIDGE_SECRET")
    SEED_EMAIL = _env("ERP_MASTER_SEED_EMAIL", "osvaldolirac@gmail.com")
    SEED_PASSWORD = _env("ERP_MASTER_SEED_PASSWORD", "Erpmaster2026")
'''


def main() -> None:
    if not TAD_EXT.is_file():
        raise SystemExit(f"Missing backup: {TAD_EXT}")

    shutil.copy2(CONFIG, CONFIG.with_suffix(f".py.bak_restore_{STAMP}"))
    shutil.copy2(TAD, TAD.with_suffix(f".py.bak_restore_{STAMP}"))

    CONFIG.write_text(CONFIG_TEXT, encoding="utf-8")
    print("config.py: restored full tenant list")

    text = TAD_EXT.read_text(encoding="utf-8")
    if "ROLES_GLOBALGAP" not in text:
        anchor = "ROLES_COMERCIAL = "
        pos = text.find(anchor)
        if pos < 0:
            raise SystemExit("ROLES_COMERCIAL anchor not found")
        text = text[:pos] + GLOBALGAP_BLOCK + "\n" + text[pos:]

    for old, new, label in (
        (MENU_PATCH_OLD, MENU_PATCH_NEW, "menu_for"),
        (ROLES_PATCH_OLD, ROLES_PATCH_NEW, "roles_for"),
        (PROT_PATCH_OLD, PROT_PATCH_NEW, "protected_role"),
    ):
        if old not in text:
            if new.split("\n", 1)[0] in text:
                print(f"{label}: already patched")
            else:
                raise SystemExit(f"{label}: anchor not found")
        else:
            text = text.replace(old, new, 1)
            print(f"{label}: ok")

    TAD.write_text(text, encoding="utf-8")
    print("tenant_admin.py: restored from extender + globalgap")

    # globalgap DB clonada desde demo: sin solo_lectura / mail_petroleo
    tad_text = TAD.read_text(encoding="utf-8")
    lu_old = '        if kind == "demo":\n            rows = conn.execute('
    lu_new = '        if kind in {"demo", "globalgap"}:\n            rows = conn.execute('
    if lu_old in tad_text:
        TAD.write_text(tad_text.replace(lu_old, lu_new, 1), encoding="utf-8")
        print("list_users globalgap: ok")


if __name__ == "__main__":
    main()
