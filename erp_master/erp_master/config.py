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
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12h

    DATABASE = _env("ERP_MASTER_DB", "/root/erp_master.db")
    BRAND_NAME = "ERP Master"
    BRAND_TAGLINE = "Super consola · Super Admin y Administrador"

    # Home links — includes Río Maipo for access only (no admin yet).
    TENANTS = [
        {
            "slug": "concepcion",
            "nombre": "La Concepción",
            "descripcion": "ERP agrícola en producción",
            "url": "/laconcepcion/",
            "estado": "activo",
        },
        {
            "slug": "demo",
            "nombre": "DEMO Agrícola",
            "descripcion": "Entorno de prueba e invitaciones",
            "url": "/demo/",
            "estado": "activo",
        },
        {
            "slug": "riomaipo",
            "nombre": "Río Maipo",
            "descripcion": "Cotizaciones y cobranza",
            "url": "/riomaipo/",
            "estado": "activo",
        },
    ]

    # Administered from master (Río Maipo excluded until later).
    ADMIN_TENANTS = [
        {
            "slug": "concepcion",
            "nombre": "La Concepción",
            "kind": "lc",
            "db": _env("ERP_LC_DB", "/root/erp_concepcion_v6.db"),
            "url": "/laconcepcion/",
            "url_admin": "/laconcepcion/m/admin",
        },
        {
            "slug": "demo",
            "nombre": "DEMO Agrícola",
            "kind": "demo",
            "db": _env("ERP_DEMO_DB", "/root/demo/erp_demo.db"),
            "url": "/demo/",
            "url_admin": "/demo/m/admin",
        },
    ]

    # Flags de estado por cliente (mantención, etc.)
    STATUS_DIR = _env("ERP_STATUS_DIR", "/root/erp_status")

    # Seed only if the DB has no users yet.
    SEED_EMAIL = _env("ERP_MASTER_SEED_EMAIL", "osvaldolirac@gmail.com")
    SEED_PASSWORD = _env("ERP_MASTER_SEED_PASSWORD", "Erpmaster2026")
