from __future__ import annotations

import os
import secrets


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


class Config:
    SECRET_KEY = _env("ERP_MASTER_SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Secure cookies when behind HTTPS (nginx terminates TLS)
    SESSION_COOKIE_SECURE = _env("ERP_MASTER_COOKIE_SECURE", "1") in {"1", "true", "yes"}
    # Consola pública en erpmaster.cl/consola/
    SESSION_COOKIE_PATH = _env("ERP_MASTER_COOKIE_PATH", "/consola")
    APPLICATION_ROOT = _env("ERP_MASTER_APPLICATION_ROOT", "/consola")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # techo absoluto 12h
    # Inactividad real (el polling de /api/host-stats NO renueva actividad).
    SESSION_IDLE_SECONDS = int(_env("ERP_MASTER_SESSION_IDLE", str(1200)))  # 20 min
    SESSION_IDLE_WARN_SECONDS = int(_env("ERP_MASTER_SESSION_IDLE_WARN", str(120)))  # aviso previo

    DATABASE = _env("ERP_MASTER_DB", "/root/erp_master.db")
    BRAND_NAME = "ERP Master"
    BRAND_TAGLINE = "Super consola · Super Admin y Administrador"

    # Home links — includes Río Maipo for access only (no admin yet).
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
            "descripcion": "Obras, APU y precios · demo",
            "producto": "constructora",
            "url": "/constructora/",
            "url_dashboard": "/constructora/",
            "estado": "activo",
        },
    ]

    # Administered from master (agrícola + comercial).
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
            "db": _env(
                "CONSTRUCTORA_DEMO_DB",
                "/root/constructora/data/constructora_demo.db",
            ),
            "secrets": _env(
                "CONSTRUCTORA_DEMO_SECRETS",
                "/root/constructora/secrets.toml",
            ),
            "nombre_erp": "DEMO Constructora",
            "url": "/constructora/",
            "url_dashboard": "/constructora/",
        },
    ]

    # Flags de estado por cliente (mantención, etc.)
    STATUS_DIR = _env("ERP_STATUS_DIR", "/root/erp_status")

    # Secreto compartido con los ERP (LC/DEMO) para Abrir ERP → dashboard autenticado.
    BRIDGE_SECRET = _env("ERP_MASTER_BRIDGE_SECRET")

    # Seed only if the DB has no users yet.
    SEED_EMAIL = _env("ERP_MASTER_SEED_EMAIL", "osvaldolirac@gmail.com")
    SEED_PASSWORD = _env("ERP_MASTER_SEED_PASSWORD", "Erpmaster2026")
