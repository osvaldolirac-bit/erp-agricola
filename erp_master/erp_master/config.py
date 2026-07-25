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
    BRAND_TAGLINE = "Consola de clientes"

    # Tenants are links only — each ERP keeps its own login/session/DB.
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

    # Seed only if the DB has no users yet.
    SEED_EMAIL = _env("ERP_MASTER_SEED_EMAIL", "osvaldolirac@gmail.com")
    SEED_PASSWORD = _env("ERP_MASTER_SEED_PASSWORD", "Erpmaster2026")
