#!/usr/bin/env python3
"""Verificación obligatoria tenant El Espino (post-deploy y cron).

Falla (exit 1) si:
- Falta flag bitácora, secrets o DB
- Cron respaldo no incluye Espino
- Reglas de negocio LC aplicadas por error a Espino
- Compras pendientes no coinciden con lo visible en Tesorería
- Hay facturas ocultas por imputación Costos (bug LC en tenant Espino)

Uso:
  APP_ROOT=/root/demo-web python3 scripts/verify_espino.py
  python3 /root/scripts/verify_espino.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(os.environ.get("APP_ROOT", "/root/demo-web"))
ESPINO_DB = Path(os.environ.get("ERP_ESPINO_DB", "/root/espino/erp_espino.db"))
ESPINO_SECRETS = Path(
    os.environ.get("ERP_ESPINO_SECRETS", "/root/espino/.streamlit/secrets.toml")
)
STATUS_DIR = Path(os.environ.get("ERP_STATUS_DIR", "/root/erp_status"))
CRON_SCRIPT = Path(os.environ.get("ERP_RESPALDO_CRON", "/root/scripts/erp_respaldo_cron.py"))
BITACORA_FLAG = STATUS_DIR / "espino.bitacora"


class CheckFailed(Exception):
    pass


def _ensure_app_path() -> None:
    root = str(APP_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@contextmanager
def _espino_tenant():
    """Simula request tenant Espino para funciones que leen g/session."""
    _ensure_app_path()
    with patch("demo_web.services.tenant_scope.tenant_slug", return_value="espino"):
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=True):
            yield


@contextmanager
def _lc_tenant():
    _ensure_app_path()
    with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=False):
            with patch("demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True):
                yield


def check_tenant_registry() -> None:
    _ensure_app_path()
    from demo_web.tenants import get_tenant

    t = get_tenant("espino")
    if not t or not t.get("db"):
        raise CheckFailed("tenants.py no registra espino o falta db")
    print("OK  tenants.py registra espino")


def check_bitacora_flag() -> None:
    if not BITACORA_FLAG.is_file():
        raise CheckFailed(f"falta flag bitácora: {BITACORA_FLAG}")
    body = BITACORA_FLAG.read_text(encoding="utf-8").strip()
    if body not in ("1", "true", "yes", "on"):
        raise CheckFailed(f"bitácora inactiva en {BITACORA_FLAG}: {body!r}")
    print(f"OK  bitácora activa ({BITACORA_FLAG})")


def check_secrets() -> None:
    if not ESPINO_SECRETS.is_file():
        raise CheckFailed(f"faltan secrets Espino: {ESPINO_SECRETS}")
    print(f"OK  secrets Espino ({ESPINO_SECRETS})")


def check_db() -> None:
    if not ESPINO_DB.is_file():
        raise CheckFailed(f"falta DB Espino: {ESPINO_DB}")
    try:
        conn = sqlite3.connect(f"file:{ESPINO_DB}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM facturas LIMIT 1")
        conn.close()
    except sqlite3.Error as exc:
        raise CheckFailed(f"DB Espino ilegible: {exc}") from exc
    print(f"OK  DB Espino ({ESPINO_DB})")


def check_respaldo_cron() -> None:
    from respaldo_cron_tenants import verify_respaldo_cron

    verify_respaldo_cron(CRON_SCRIPT, slug_filter={"espino"})
    print(f"OK  cron respaldo incluye Espino ({CRON_SCRIPT})")


def check_tenant_rules_code() -> None:
    _ensure_app_path()
    from demo_web.services.tenant_rules import verify_implementation_errors

    errors = verify_implementation_errors()
    if errors:
        raise CheckFailed("tenant_rules: " + "; ".join(errors))
    print("OK  reglas código Espino vs LC (tenant_rules)")


def _cxp_rows_espino(conn: sqlite3.Connection) -> list[tuple]:
    _ensure_app_path()
    from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino
    from demo_web.services.tesoreria_cxp import (
        saldo_factura_tesoreria,
        sql_imputado_costos_subquery,
        sql_solo_cxp_tesoreria,
    )

    imp_sql = sql_imputado_costos_subquery("f")
    excl = sql_and_excluir_razon_social_espino("razon_social", alias="f")
    with _espino_tenant():
        sql = f"""
            SELECT f.id, f.nro_documento, f.proveedor, f.monto_total,
                   COALESCE(f.monto_pagado, 0) AS monto_pagado,
                   {imp_sql} AS imputado_costos
            FROM facturas f
            WHERE f.estado='Pendiente' AND f.monto_total > 0
              {sql_solo_cxp_tesoreria('f')}
              {excl}
        """
        rows = conn.execute(sql).fetchall()

    visible = []
    hidden_lc = []
    for row in rows:
        _id, nro, prov, total, pagado, imp = row
        bruto = max(0.0, float(total or 0) - float(pagado or 0))
        saldo = saldo_factura_tesoreria(total, pagado, imp)
        if saldo > 0.01:
            visible.append((nro, prov, bruto, saldo, float(imp or 0)))
        elif bruto > 0.01 and float(imp or 0) > 0.01:
            hidden_lc.append((nro, prov, bruto, float(imp or 0)))
    return visible, hidden_lc


def check_cxp_parity_db() -> None:
    conn = sqlite3.connect(f"file:{ESPINO_DB}?mode=ro", uri=True)
    try:
        visible, hidden_lc = _cxp_rows_espino(conn)
        if hidden_lc:
            sample = ", ".join(f"{n}/{p}" for n, p, _, _ in hidden_lc[:5])
            raise CheckFailed(
                f"{len(hidden_lc)} factura(s) ocultas por regla LC (imputación Costos): {sample}"
            )

        dupes = conn.execute(
            """
            SELECT nro_documento, proveedor, COUNT(*) AS n
            FROM facturas
            WHERE estado='Pendiente' AND monto_total > 0
            GROUP BY nro_documento, proveedor
            HAVING n > 1
            """
        ).fetchall()
        if dupes:
            sample = ", ".join(f"{r[0]}/{r[1]}×{r[2]}" for r in dupes[:5])
            raise CheckFailed(f"duplicados pendientes en Compras: {sample}")

        total_saldo = sum(r[3] for r in visible)
        print(
            f"OK  CxP Espino: {len(visible)} pendiente(s), saldo ${total_saldo:,.0f}"
        )
    finally:
        conn.close()


def check_compras_module_loader() -> None:
    _ensure_app_path()
    os.environ.setdefault("ERP_APP", "agricola")
    from demo_web.wsgi import app
    from demo_web.services.erp_loader import bind_tenant_context

    with app.test_request_context("/"):
        with patch(
            "demo_web.services.mantenimiento.ensure_bitacora_erp_activa", return_value=True
        ):
            t = bind_tenant_context("espino")
        if not t or t.get("slug") != "espino":
            raise CheckFailed("bind_tenant_context('espino') falló")
    print("OK  erp_loader bind tenant espino")


def check_master_brand_logo() -> None:
    _ensure_app_path()
    from demo_web.services.branding import find_master_logo_path, master_logo_data_uri

    path = find_master_logo_path()
    if not path or not path.is_file():
        raise CheckFailed("logo ERP Master no encontrado en disco")
    uri = master_logo_data_uri()
    if not uri or not uri.startswith("data:image/"):
        raise CheckFailed("master_logo_data_uri no genera imagen")
    print(f"OK  logo ERP Master ({path.name}, {len(uri)} bytes data-uri)")


def check_master_brand_markup() -> None:
    """Logo Espino/LC: template, CSS ::after y JS fallback presentes en deploy."""
    root = APP_ROOT / "demo_web"
    css_path = root / "static/css/erp.css"
    js_path = root / "static/js/demo.js"
    base_path = root / "templates/base.html"
    dash_path = root / "templates/dashboard/index.html"
    for p in (css_path, js_path, base_path, dash_path):
        if not p.is_file():
            raise CheckFailed(f"falta archivo logo: {p}")
    css = css_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")
    base = base_path.read_text(encoding="utf-8")
    dash = dash_path.read_text(encoding="utf-8")
    if "tenant-espino::after" not in css:
        raise CheckFailed("erp.css sin fallback CSS tenant-espino")
    if "ensureErpMasterBrand" not in js:
        raise CheckFailed("demo.js sin ensureErpMasterBrand")
    if "data-erp-master-brand" not in base or "body_tenant_class" not in base:
        raise CheckFailed("base.html sin marcadores logo multi-capa")
    if "show_master = show_master_brand" not in dash:
        raise CheckFailed("dashboard/index.html sin fallback logo Espino")
    print("OK  markup logo ERP Master (CSS + JS + templates)")


def main() -> int:
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    checks = [
        check_tenant_registry,
        check_bitacora_flag,
        check_secrets,
        check_db,
        check_respaldo_cron,
        check_tenant_rules_code,
        check_master_brand_logo,
        check_master_brand_markup,
        check_compras_module_loader,
        check_cxp_parity_db,
    ]
    failed = 0
    for fn in checks:
        try:
            fn()
        except CheckFailed as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
    if failed:
        print(
            f"\n{failed} check(s) Espino fallaron — deploy debe abortar",
            file=sys.stderr,
        )
        return 1
    print("\nAll Espino checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
