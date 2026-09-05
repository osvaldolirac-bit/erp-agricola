#!/usr/bin/env python3
"""DEPRECATED — el cron lee tenants desde demo_web.tenants vía respaldo_cron_clientes.

Antes parcheaba a mano la lista CLIENTES en /root/scripts/erp_respaldo_cron.py.
Ahora basta con deploy-demo-web.sh, que sincroniza el cron versionado.
"""
from __future__ import annotations

import sys


def main() -> int:
    print(
        "DEPRECATED: patch_espino_respaldo_cron ya no es necesario.\n"
        "El cron usa demo_web.services.respaldo_cron_clientes.clientes_respaldo_datos().\n"
        "Ejecute /root/scripts/deploy-demo-web.sh para actualizar erp_respaldo_cron.py.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
