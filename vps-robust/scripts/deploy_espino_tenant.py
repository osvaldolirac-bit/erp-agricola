#!/usr/bin/env python3
"""Deploy tenant El Espino en VPS (solo suma; no toca La Concepción)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
DEMO_WEB = Path("/root/demo-web")
ERP_MASTER = Path("/root/erp_master")
BACKUP = Path(f"/root/backups/espino-tenant/{datetime.now().strftime('%Y%m%d_%H%M%S')}")

FILES = [
    (WORKSPACE / "demo_web/tenants.py", DEMO_WEB / "demo_web/tenants.py"),
    (WORKSPACE / "demo_web/services/erp_loader.py", DEMO_WEB / "demo_web/services/erp_loader.py"),
    (WORKSPACE / "demo_web/templates/dashboard/index.html", DEMO_WEB / "demo_web/templates/dashboard/index.html"),
    (WORKSPACE / "demo_web/templates/modules/administracion.html", DEMO_WEB / "demo_web/templates/modules/administracion.html"),
    (WORKSPACE / "demo_web/templates/modules/petroleo.html", DEMO_WEB / "demo_web/templates/modules/petroleo.html"),
    (WORKSPACE / "demo_web/templates/salida_petroleo/form.html", DEMO_WEB / "demo_web/templates/salida_petroleo/form.html"),
    (WORKSPACE / "demo_web/blueprints/salida_petroleo.py", DEMO_WEB / "demo_web/blueprints/salida_petroleo.py"),
    (WORKSPACE / "demo-web/app_concepcion.py", DEMO_WEB / "app_concepcion.py"),
    (WORKSPACE / "demo_web/services/branding.py", DEMO_WEB / "demo_web/services/branding.py"),
    (WORKSPACE / "demo_web/services/tenant_scope.py", DEMO_WEB / "demo_web/services/tenant_scope.py"),
    (WORKSPACE / "demo_web/services/native/petroleo.py", DEMO_WEB / "demo_web/services/native/petroleo.py"),
    (WORKSPACE / "demo_web/services/native/tesoreria.py", DEMO_WEB / "demo_web/services/native/tesoreria.py"),
    (WORKSPACE / "demo_web/services/native/espino_bodega.py", DEMO_WEB / "demo_web/services/native/espino_bodega.py"),
    (WORKSPACE / "demo_web/services/native/bodega.py", DEMO_WEB / "demo_web/services/native/bodega.py"),
    (WORKSPACE / "demo_web/services/native/_helpers.py", DEMO_WEB / "demo_web/services/native/_helpers.py"),
    (WORKSPACE / "demo_web/services/dashboard.py", DEMO_WEB / "demo_web/services/dashboard.py"),
    (WORKSPACE / "erp_master/erp_master/config.py", ERP_MASTER / "erp_master/config.py"),
    (WORKSPACE / "scripts/bootstrap_espino_tenant.py", DEMO_WEB / "scripts/bootstrap_espino_tenant.py"),
    (WORKSPACE / "scripts/migrate_lc_to_espino_tenant.py", DEMO_WEB / "scripts/migrate_lc_to_espino_tenant.py"),
    (WORKSPACE / "scripts/sync_espino_users_from_lc.py", DEMO_WEB / "scripts/sync_espino_users_from_lc.py"),
    (WORKSPACE / "demo_web/auth/decorators.py", DEMO_WEB / "demo_web/auth/decorators.py"),
    (WORKSPACE / "demo_web/services/native/globalgap.py", DEMO_WEB / "demo_web/services/native/globalgap.py"),
]


def main() -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    for src, dst in FILES:
        if dst.is_file():
            rel = dst.relative_to(dst.anchor) if dst.is_absolute() else dst
            bkp = BACKUP / str(rel).lstrip("/")
            bkp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bkp)
        if not src.is_file():
            print(f"MISSING source: {src}", file=sys.stderr)
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"copied {src.name} -> {dst}")

    subprocess.run(
        [sys.executable, str(DEMO_WEB / "scripts/migrate_lc_to_espino_tenant.py")],
        check=True,
    )
    for svc in ("erp-agricola-web", "erp-lc-web", "erp-demo-web", "erp-master-web"):
        subprocess.run(["systemctl", "reload", svc], check=False)
    print("deploy espino tenant: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
