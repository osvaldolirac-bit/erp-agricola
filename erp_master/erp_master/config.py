from __future__ import annotations

import os
import secrets


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


class Config:
    SECRET_KEY = _env("ERP_MASTER_SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_NAME = _env("ERP_MASTER_SESSION_COOKIE", "erp_master_session_v2")
    SESSION_COOKIE_PATH = _env("ERP_MASTER_SESSION_COOKIE_PATH", "/consola")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env("ERP_MASTER_COOKIE_SECURE", "1") in {"1", "true", "yes"}
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # techo absoluto 12h
    SESSION_IDLE_SECONDS = int(_env("ERP_MASTER_SESSION_IDLE", str(7200)))
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
            "slug": "taller-demo",
            "nombre": "DEMO Taller Automotriz",
            "descripcion": "Pruebas · Taller automotriz (cotizaciones + OT)",
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
            "slug": "taller-demo",
            "nombre": "DEMO Taller Automotriz",
            "kind": "comercial",
            "producto": "comercial",
            "es_demo": True,
            "rubro": "taller",
            "db": _env("TALLER_DEMO_DB", "/root/riomaipo/data/taller_demo.db"),
            "secrets": _env(
                "TALLER_DEMO_SECRETS", "/root/riomaipo/secrets_taller_demo.toml"
            ),
            "nombre_erp": "DEMO Taller Automotriz",
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
