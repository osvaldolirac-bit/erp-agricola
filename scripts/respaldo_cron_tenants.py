#!/usr/bin/env python3
"""Fuente única: tenants agrícola con DB → cron respaldo.

Verifica que erp_respaldo_cron.py liste cada tenant operativo.
Con --sync inserta entradas faltantes (idempotente).

Uso:
  python3 scripts/respaldo_cron_tenants.py
  python3 scripts/respaldo_cron_tenants.py --sync
  python3 scripts/respaldo_cron_tenants.py --cron /root/scripts/erp_respaldo_cron.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

APP_ROOT = Path(os.environ.get("APP_ROOT", "/root/demo-web"))


class CronCheckFailed(Exception):
    pass


def _tenant_backups() -> list[dict[str, str]]:
    root = str(APP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from demo_web.tenants import list_tenants

    out = []
    for t in list_tenants():
        db = (t.get("db") or "").strip()
        if not db or t.get("kind") == "demo":
            continue
        out.append(
            {
                "slug": t["slug"],
                "nombre": t.get("nombre_erp") or t.get("nombre") or t["slug"],
                "db": db,
                "secrets": (t.get("secrets") or "").strip(),
                "producto": "agricola",
            }
        )
    return out


def _entry_block(item: dict[str, str]) -> str:
    sec = item.get("secrets") or '""'
    return f"""    {{
        "nombre": "{item["nombre"]}",
        "db": "{item["db"]}",
        "secrets": "{sec}",
        "producto": "{item["producto"]}",
    }},
"""


def verify_respaldo_cron(
    cron_path: Path,
    *,
    slug_filter: set[str] | None = None,
) -> None:
    if not cron_path.is_file():
        raise CronCheckFailed(f"cron respaldo no existe: {cron_path}")
    text = cron_path.read_text(encoding="utf-8")
    missing = []
    for item in _tenant_backups():
        if slug_filter and item["slug"] not in slug_filter:
            continue
        if item["db"] not in text:
            missing.append(item["slug"])
    if missing:
        raise CronCheckFailed(
            f"cron {cron_path} sin DB de: {', '.join(missing)} "
            f"(ejecute respaldo_cron_tenants.py --sync)"
        )


def sync_respaldo_cron(cron_path: Path) -> list[str]:
    if not cron_path.is_file():
        raise CronCheckFailed(f"cron respaldo no existe: {cron_path}")
    text = cron_path.read_text(encoding="utf-8")
    added: list[str] = []
    for item in _tenant_backups():
        if item["db"] in text:
            continue
        marker = '"producto": "agricola",\n    },'
        block = _entry_block(item)
        if marker not in text:
            raise CronCheckFailed(
                f"no se encontró ancla para insertar {item['slug']} en {cron_path}"
            )
        text = text.replace(marker, f'"producto": "agricola",\n    }},\n{block}', 1)
        added.append(item["slug"])
    if added:
        cron_path.write_text(text, encoding="utf-8")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificar/sincronizar cron respaldo tenants")
    parser.add_argument(
        "--cron",
        default=os.environ.get("ERP_RESPALDO_CRON", "/root/scripts/erp_respaldo_cron.py"),
    )
    parser.add_argument("--sync", action="store_true", help="Insertar tenants faltantes")
    parser.add_argument("--slug", action="append", default=[], help="Solo estos slugs")
    args = parser.parse_args()
    cron_path = Path(args.cron)
    slug_filter = set(args.slug) if args.slug else None

    try:
        if args.sync:
            added = sync_respaldo_cron(cron_path)
            if added:
                print(f"OK  cron sync: agregados {', '.join(added)}")
            else:
                print("OK  cron sync: nada que agregar")
        verify_respaldo_cron(cron_path, slug_filter=slug_filter)
        print(f"OK  cron respaldo alineado con tenants.py ({cron_path})")
    except CronCheckFailed as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
