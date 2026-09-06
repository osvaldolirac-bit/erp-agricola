#!/usr/bin/env python3
"""Bootstrap idempotente Espino antes de verify/deploy.

Repara estado VPS típico (sin tocar datos operativos):
- Flag bitácora /root/erp_status/espino.bitacora
- Cron respaldo alineado con tenants.py
- Secrets mínimos si faltan

Uso:
  python3 scripts/ensure_espino_operativo.py
  APP_ROOT=/root/demo-web python3 /root/scripts/ensure_espino_operativo.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_ROOT = Path(os.environ.get("APP_ROOT", "/root/demo-web"))
STATUS_DIR = Path(os.environ.get("ERP_STATUS_DIR", "/root/erp_status"))
ESPINO_SECRETS = Path(
    os.environ.get("ERP_ESPINO_SECRETS", "/root/espino/.streamlit/secrets.toml")
)
LC_SECRETS = Path(os.environ.get("ERP_LC_SECRETS", "/root/.streamlit/secrets.toml"))
CRON_SCRIPT = Path(os.environ.get("ERP_RESPALDO_CRON", "/root/scripts/erp_respaldo_cron.py"))


def ensure_bitacora() -> bool:
    flag = STATUS_DIR / "espino.bitacora"
    flag.parent.mkdir(parents=True, exist_ok=True)
    if flag.is_file():
        body = flag.read_text(encoding="utf-8").strip()
        if body in ("1", "true", "yes", "on"):
            return False
    flag.write_text("1\n", encoding="utf-8")
    print(f"FIX  bitácora activada: {flag}")
    return True


def ensure_secrets() -> bool:
    if ESPINO_SECRETS.is_file():
        return False
    ESPINO_SECRETS.parent.mkdir(parents=True, exist_ok=True)
    if LC_SECRETS.is_file():
        shutil.copy2(LC_SECRETS, ESPINO_SECRETS)
        print(f"FIX  secrets copiados LC → {ESPINO_SECRETS}")
    else:
        ESPINO_SECRETS.write_text("# SMTP opcional\n", encoding="utf-8")
        print(f"FIX  secrets placeholder: {ESPINO_SECRETS}")
    return True


def ensure_cron() -> bool:
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    if not CRON_SCRIPT.is_file():
        print(f"SKIP cron (no existe {CRON_SCRIPT})")
        return False
    from respaldo_cron_tenants import sync_respaldo_cron

    added = sync_respaldo_cron(CRON_SCRIPT)
    if added:
        print(f"FIX  cron respaldo: {', '.join(added)}")
        return True
    return False


def ensure_erp_loader_hook() -> None:
    root = str(APP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from demo_web.services.mantenimiento import ensure_bitacora_erp_activa

        ensure_bitacora_erp_activa("espino")
    except Exception as exc:
        print(f"WARN ensure_bitacora_erp_activa: {exc}", file=sys.stderr)


def main() -> int:
    changed = False
    changed |= ensure_bitacora()
    changed |= ensure_secrets()
    changed |= ensure_cron()
    ensure_erp_loader_hook()
    if changed:
        print("ensure_espino_operativo: reparaciones aplicadas")
    else:
        print("ensure_espino_operativo: ya operativo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
