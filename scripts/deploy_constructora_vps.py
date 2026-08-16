#!/usr/bin/env python3
"""Deploy fixes bitácora + respaldo constructora en VPS (ejecutar en el servidor)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

ERP_RESPALDO = Path("/root/erp_respaldo.py")
CRON = Path("/root/scripts/erp_respaldo_cron.py")
SYSTEMD = Path("/etc/systemd/system/erp-constructora.service")
CONSTRUCTORA_PY = Path("/root/constructora/rmweb/constructora.py")
SUPER_CONSOLA = Path("/root/erp_master/erp_master/templates/super_consola.html")
BITACORA_FLAG = Path("/root/erp_status/constructora-demo.bitacora")
DB_DEMO = Path("/root/constructora/data/constructora_demo.db")

CONSTRUCTORA_SPEC = '''    "constructora": {
        "nombre": "Codigo Constructora",
        "slug": "constructora",
        "producto": "constructora",
        "db": "/root/constructora/data/constructora_demo.db",
        "secrets": "/root/constructora/secrets_constructora_demo.toml",
        "roots": [
            {"path": "/root/constructora", "recursive": True},
            {
                "path": "/etc/systemd/system",
                "files": ["erp-constructora.service"],
            },
        ],
    },'''

CRON_ENTRY = """    {
        "nombre": "DEMO Constructora",
        "db": "/root/constructora/data/constructora_demo.db",
        "secrets": "/root/constructora/secrets_constructora_demo.toml",
        "producto": "constructora",
    },
"""


def patch_erp_respaldo() -> None:
    text = ERP_RESPALDO.read_text(encoding="utf-8")
    text = re.sub(
        r'"constructora":\s*\{[^}]+\}(?:\s*,\s*\{[^}]+\})*?\s*\},',
        CONSTRUCTORA_SPEC,
        text,
        count=1,
        flags=re.DOTALL,
    )
    ERP_RESPALDO.write_text(text, encoding="utf-8")
    print("erp_respaldo.py: spec constructora OK")


def patch_cron() -> None:
    text = CRON.read_text(encoding="utf-8")
    if "DEMO Constructora" in text:
        print("erp_respaldo_cron.py: ya incluye constructora")
        return
    needle = '        "producto": "comercial",\n    },\n]'
    if needle not in text:
        raise SystemExit("cron CLIENTES block not found")
    CRON.write_text(
        text.replace(
            '        "producto": "comercial",\n    },\n]',
            '        "producto": "comercial",\n    },\n' + CRON_ENTRY + ']',
            1,
        ),
        encoding="utf-8",
    )
    print("erp_respaldo_cron.py: DEMO Constructora agregado")


def patch_systemd() -> None:
    text = SYSTEMD.read_text(encoding="utf-8")
    new = re.sub(
        r"Environment=RIOMAIPO_DB=.*",
        "Environment=RIOMAIPO_DB=/root/constructora/data/constructora_demo.db",
        text,
    )
    SYSTEMD.write_text(new, encoding="utf-8")
    print("erp-constructora.service: RIOMAIPO_DB → constructora_demo.db")


def patch_constructora_py() -> None:
    text = CONSTRUCTORA_PY.read_text(encoding="utf-8")
    if "from rmweb import bitacora" not in text:
        text = text.replace(
            "from rmweb import obra_contrato as obractx\n",
            "from rmweb import obra_contrato as obractx\nfrom rmweb import bitacora as bit\n",
            1,
        )
    if "bit.ensure_bitacora_schema" not in text:
        text = text.replace(
            "    obractx.ensure_obra_contrato_schema(c)\n",
            "    obractx.ensure_obra_contrato_schema(c)\n    bit.ensure_bitacora_schema(c)\n",
            1,
        )
    CONSTRUCTORA_PY.write_text(text, encoding="utf-8")
    print("constructora.py: bitácora schema OK")


def patch_super_consola() -> None:
    text = SUPER_CONSOLA.read_text(encoding="utf-8")
    old = "{% if tenant.kind != 'comercial' %}"
    new = "{% if tenant.kind != 'comercial' or tenant.producto == 'constructora' %}"
    if old not in text:
        print("super_consola.html: bitácora ERP ya parcheada o bloque distinto")
        return
    SUPER_CONSOLA.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("super_consola.html: bitácora ERP visible para constructora")


def enable_bitacora_flag() -> None:
    BITACORA_FLAG.parent.mkdir(parents=True, exist_ok=True)
    BITACORA_FLAG.write_text("1\n", encoding="utf-8")
    print("constructora-demo.bitacora → activa")


def ensure_respaldo_meta() -> None:
    conn = sqlite3.connect(DB_DEMO, timeout=30)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (clave TEXT PRIMARY KEY, valor TEXT)"
        )
        rows = {
            "respaldo_email": "osvaldolirac@gmail.com",
            "respaldo_activo": "1",
            "respaldo_frecuencia": "diario",
            "respaldo_codigo_frecuencia": "semanal",
        }
        for k, v in rows.items():
            conn.execute(
                "INSERT INTO schema_meta (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (k, v),
            )
        conn.commit()
    finally:
        conn.close()
    print("constructora_demo.db: respaldo activo OK")


def main() -> None:
    patch_erp_respaldo()
    patch_cron()
    patch_systemd()
    patch_constructora_py()
    patch_super_consola()
    enable_bitacora_flag()
    ensure_respaldo_meta()
    print("done")


if __name__ == "__main__":
    main()
