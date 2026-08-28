#!/usr/bin/env python3
"""Agrega tenant GlobalGAP sin pisar consola completa (merge config + tenant_admin).

Uso en VPS después de desplegar código agrícola:
  python3 patch_globalgap_consola_merge.py
  systemctl restart erp-master-web erp-agricola-web
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/root/erp_master/erp_master")
CONFIG = ROOT / "config.py"
TAD = ROOT / "tenant_admin.py"
STAMP = datetime.now().strftime("%Y%m%d%H%M%S")

GLOBALGAP_TENANT = """
        {
            "slug": "globalgap",
            "nombre": "GlobalGAP Consultor",
            "descripcion": "Certificación multi-cliente",
            "producto": "agricola",
            "url": "/agricola/globalgap/",
            "url_dashboard": "/agricola/globalgap/panel",
            "estado": "activo",
        },"""

GLOBALGAP_ADMIN = """
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
        },"""

GLOBALGAP_TAD = '''
ROLES_GLOBALGAP = ("admin",)

MENU_GLOBALGAP = [
    ("Panel consultor", "PanelGlobalGAP"),
    ("GlobalGAP", "GlobalGAP"),
    ("Soporte", "Soporte"),
    ("Manual", "Manual"),
]
'''


def backup(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak_{STAMP}"))


def ensure_globalgap_config(text: str) -> str:
    if '"slug": "globalgap"' in text:
        print("config: globalgap already present")
        return text
    if '"slug": "demo"' not in text:
        raise SystemExit("config: demo anchor missing")
    text = text.replace(
        '"slug": "demo"',
        '"slug": "demo"',
        1,
    )
    # insert after demo block in TENANTS (after demo closing },)
    text = re.sub(
        r'("slug": "demo",[\s\S]*?"estado": "activo",\s*\},)',
        r"\1" + GLOBALGAP_TENANT,
        text,
        count=1,
    )
    text = re.sub(
        r'("slug": "demo",[\s\S]*?"url_admin": "[^"]+",\s*\},)',
        r"\1" + GLOBALGAP_ADMIN,
        text,
        count=1,
    )
    print("config: globalgap merged")
    return text


def ensure_globalgap_tad(text: str) -> str:
    if "ROLES_GLOBALGAP" in text:
        print("tenant_admin: globalgap already present")
        return text
    anchor = "ROLES_COMERCIAL = "
    pos = text.find(anchor)
    if pos < 0:
        anchor = "ROLES_DEMO = "
        pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("tenant_admin: roles anchor missing")
    text = text[:pos] + GLOBALGAP_TAD + "\n" + text[pos:]
    for old, new in (
        (
            '    if kind == "lc":\n        return list(MENU_LC)',
            '    if kind == "globalgap":\n        return list(MENU_GLOBALGAP)\n    if kind == "lc":\n        return list(MENU_LC)',
        ),
        (
            '    if kind == "lc":\n        return ROLES_LC',
            '    if kind == "globalgap":\n        return ROLES_GLOBALGAP\n    if kind == "lc":\n        return ROLES_LC',
        ),
        (
            '    if kind == "lc":\n        return "admin"',
            '    if kind == "globalgap":\n        return "admin"\n    if kind == "lc":\n        return "admin"',
        ),
        (
            '        if kind == "demo":\n            rows = conn.execute(',
            '        if kind in {"demo", "globalgap"}:\n            rows = conn.execute(',
        ),
    ):
        if old in text and new.split("\n", 1)[0] not in text:
            text = text.replace(old, new, 1)
    print("tenant_admin: globalgap merged")
    return text


def main() -> None:
    backup(CONFIG)
    backup(TAD)
    cfg = ensure_globalgap_config(CONFIG.read_text(encoding="utf-8"))
    CONFIG.write_text(cfg, encoding="utf-8")
    tad = ensure_globalgap_tad(TAD.read_text(encoding="utf-8"))
    TAD.write_text(tad, encoding="utf-8")
    print("OK — merge globalgap sin reemplazar consola completa")


if __name__ == "__main__":
    main()
