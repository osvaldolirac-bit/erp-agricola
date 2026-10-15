#!/usr/bin/env python3
"""Cron LC: ejecuta colas Hydrawise programadas (sin tener el link abierto)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from demo_web.services.erp_loader import bind_tenant_context, get_demo_module
    from demo_web.services import hydrawise_riego as hw
    from demo_web.wsgi import app

    with app.app_context():
        bind_tenant_context("concepcion")
        if not hw.hydrawise_habilitado():
            return 0
        demo = get_demo_module()
        conn = demo.conectar_db()
        try:
            if not (hw.get_api_key(conn) or "").strip():
                return 0
            if not hw._cola_activa(conn):
                return 0
            result = hw.sincronizar_hydrawise(conn, "cron-hydra", force=False)
            msg = str(result.get("msg") or "").strip()
            if msg:
                print(msg, flush=True)
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
