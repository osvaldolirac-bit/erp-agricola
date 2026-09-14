#!/usr/bin/env python3
"""Bloquea parches destructivos salvo uso explícito con --force.

Integrar al inicio de scripts peligrosos:
  from deploy_guard import require_safe_patch
  require_safe_patch(__file__)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Parches que SOBRESCRIBEN config/app completos o resetean claves sin aviso.
BLOCKED = frozenset(
    {
        "patch_consola_restore_tenants.py",
        "patch_consola_session_reset.py",
    }
)

# Parches legacy: solo en VPS con backups; preferir deploy-consola.sh
WARN_LEGACY = frozenset(
    {
        "patch_consola_vps.py",
        "patch_consola_tenant_admin.py",
        "patch_consola_login_ui.py",
        "patch_consola_login_access.py",
        "patch_consola_stale_session.py",
        "patch_consola_redirect_loop.py",
        "patch_consola_logout.py",
    }
)

ALLOW_ENV = "ERP_DEPLOY_ALLOW_DESTRUCTIVE"


def script_name(path: str | Path) -> str:
    return Path(path).name


def require_safe_patch(caller: str | Path, *, force_flag: str = "--force") -> None:
    name = script_name(caller)
    if name not in BLOCKED:
        if name in WARN_LEGACY:
            print(
                f"WARN: {name} is legacy. Prefer: erp_master/deploy/deploy-consola.sh",
                file=sys.stderr,
            )
        return

    if force_flag in sys.argv or (__import__("os").environ.get(ALLOW_ENV) == "1"):
        print(f"WARN: running BLOCKED patch {name} with explicit force", file=sys.stderr)
        return

    print(
        f"\nBLOCKED: {name}\n"
        "  Este parche sobrescribe producción o resetea claves.\n"
        "  Use deploy-consola.sh + patch_globalgap_consola_merge.py (merge only).\n"
        f"  Si realmente debe ejecutarlo: {name} {force_flag}\n"
        f"  o export {ALLOW_ENV}=1\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    for b in sorted(BLOCKED):
        print(f"blocked: {b}")
    for w in sorted(WARN_LEGACY):
        print(f"legacy:  {w}")
