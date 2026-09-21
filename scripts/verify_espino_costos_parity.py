#!/usr/bin/env python3
"""Verifica paridad Dashboard vs Costos en tenant El Espino."""
from __future__ import annotations

import sys

sys.path.insert(0, "/root/demo-web")

from demo_web.services.erp_loader import get_erp_module_for
from demo_web.services.espino_costos import verificar_parity_dashboard_costos
from demo_web.services.native._helpers import prorrateo_rrhh


def main() -> int:
    slug = (sys.argv[1] if len(sys.argv) > 1 else "espino").strip().lower()
    erp = get_erp_module_for(slug)
    conn = erp.conectar_db()
    try:
        ok, msg = verificar_parity_dashboard_costos(erp, conn, prorrateo_rrhh(erp, conn))
        print(msg)
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
