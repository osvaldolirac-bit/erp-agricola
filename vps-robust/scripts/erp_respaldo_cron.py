#!/usr/bin/env python3
"""Cron diario: respaldo de datos y código por correo — prod y demo.

Tenants agrícola: sincronizados desde demo_web.tenants (ver respaldo_cron_clientes.py).

Crontab sugerido (hora Chile, servidor UTC):
  0 3 * * * /usr/bin/python3 /root/scripts/erp_respaldo_cron.py >> /root/logs/erp_respaldo.log 2>&1
"""
from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.environ.get("ERP_DEMO_ROOT", "/root/demo-web")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from demo_web.services.respaldo_cron_clientes import clientes_respaldo_datos
from erp_respaldo import (
    SPECS_RESPALDO_CODIGO_RUBRO,
    ejecutar_respaldo,
    ejecutar_respaldo_codigo_rubro,
    email_default_desde_secrets,
    hora_chile,
    load_codigo_rubro_meta,
    migrar_config_respaldo,
)

CLIENTES = clientes_respaldo_datos()


def main() -> None:
    forzar = "--forzar" in sys.argv
    solo_codigo = "--solo-codigo" in sys.argv
    solo_datos = "--solo-datos" in sys.argv
    ahora = hora_chile()
    print(f"--- respaldo {ahora.strftime('%Y-%m-%d %H:%M:%S')} America/Santiago ---")
    codigos: list[int] = []

    if not solo_codigo:
        for cli in CLIENTES:
            db = cli["db"]
            if not os.path.isfile(db):
                print(f"SKIP DATOS {cli['nombre']}: no existe {db}")
                continue
            conn = sqlite3.connect(db, timeout=60)
            try:
                migrar_config_respaldo(conn, email_default_desde_secrets(cli["secrets"]))
                res = ejecutar_respaldo(
                    conn,
                    cli["nombre"],
                    db,
                    cli["secrets"],
                    forzar=forzar,
                    usuario="CRON",
                )
                if res.get("ok"):
                    print(f"OK DATOS {cli['nombre']} → {res.get('destinatarios')}")
                    codigos.append(0)
                elif res.get("motivo") == "no_corresponde":
                    cfg = res.get("config", {})
                    print(
                        f"SKIP DATOS {cli['nombre']}: no corresponde "
                        f"(freq={cfg.get('frecuencia')}, ultimo={cfg.get('ultimo_envio')})"
                    )
                    codigos.append(0)
                else:
                    print(f"FAIL DATOS {cli['nombre']}: {res.get('motivo')} {res.get('error', '')}")
                    codigos.append(1)
            finally:
                conn.close()

    if not solo_datos:
        for rubro in SPECS_RESPALDO_CODIGO_RUBRO.keys():
            meta = load_codigo_rubro_meta(rubro)
            res_c = ejecutar_respaldo_codigo_rubro(rubro, forzar=forzar, usuario="CRON")
            if res_c.get("ok"):
                extra = res_c.get("aviso") or "con adjunto"
                print(
                    f"OK CODIGO {rubro} → VPS {res_c.get('archivo')} · "
                    f"mail {res_c.get('destinatarios')} "
                    f"({res_c.get('archivos', 0)} archivos) · {extra}"
                )
                codigos.append(0)
            elif res_c.get("motivo") == "no_corresponde":
                cfg = res_c.get("config", {})
                print(
                    f"SKIP CODIGO {rubro}: no corresponde "
                    f"(activo={meta.get('activo')}, freq={cfg.get('frecuencia_codigo')}, "
                    f"ultimo={cfg.get('ultimo_envio_codigo')})"
                )
                codigos.append(0)
            else:
                print(
                    f"FAIL CODIGO {rubro}: {res_c.get('motivo')} "
                    f"{res_c.get('error', '')}"
                )
                codigos.append(1)

    sys.exit(1 if any(c != 0 for c in codigos) else 0)


if __name__ == "__main__":
    main()
