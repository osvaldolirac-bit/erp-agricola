from __future__ import annotations

import os
from pathlib import Path

from demo_web.tenants import (
    RUBRO_BRAND,
    RUBRO_PREFIX,
    RUBRO_SUBTITLE,
    RUBRO_TITLE,
    TENANTS,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Config:
    # Modo rubro agrícola multi-tenant
    ERP_RUBRO = "agricola"
    ERP_APP = "agricola"  # proceso; el tenant real va en sesión
    SECRET_KEY = os.environ.get("ERP_DEMO_SECRET_KEY", "agricola-dev-change-me")
    # Defaults de proceso (no sustituyen DB por-tenant)
    DATABASE_PATH = TENANTS["concepcion"]["db"]
    SECRETS_PATH = TENANTS["concepcion"]["secrets"]
    APPLICATION_ROOT = os.environ.get("ERP_DEMO_URL_PREFIX") or RUBRO_PREFIX
    SESSION_COOKIE_NAME = os.environ.get("ERP_SESSION_COOKIE", "erp_agricola_session")
    SESSION_COOKIE_PATH = (os.environ.get("ERP_DEMO_URL_PREFIX") or RUBRO_PREFIX) or "/"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("ERP_COOKIE_SECURE", "1") in {"1", "true", "yes"}
    PERMANENT_SESSION_LIFETIME = 86400 * 7
    REPO_ROOT = _REPO_ROOT

    # Pantalla de acceso común del rubro
    ERP_TITLE = os.environ.get("ERP_TITLE", RUBRO_TITLE)
    ERP_BRAND = os.environ.get("ERP_BRAND", RUBRO_BRAND)
    ERP_LOGIN_BADGE = os.environ.get("ERP_LOGIN_BADGE", "")
    ERP_LOGIN_ICON = os.environ.get("ERP_LOGIN_ICON", "")
    ERP_LOGIN_SUBTITLE = os.environ.get("ERP_LOGIN_SUBTITLE", RUBRO_SUBTITLE)

    MASTER_BRIDGE_SECRET = os.environ.get("ERP_MASTER_BRIDGE_SECRET", "")

    @staticmethod
    def static_version() -> str:
        override = os.environ.get("ERP_STATIC_VERSION")
        if override:
            return override
        static_root = Path(__file__).resolve().parent / "static"
        mtimes: list[int] = []
        for rel in (
            "css/erp.css",
            "css/salida-link.css",
            "css/globalgap.css",
            "css/planes.css",
            "js/demo.js",
        ):
            path = static_root / rel
            if path.is_file():
                mtimes.append(int(path.stat().st_mtime))
        return str(max(mtimes)) if mtimes else "1"
