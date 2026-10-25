#!/usr/bin/env python3
"""Smoke tests LC+Espino (imports y reglas críticas). Ejecutar en CI o post-deploy VPS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _imports_criticos() -> None:
    from demo_web.services import (  # noqa: F401
        bodega_kardex,
        espino_scope,
        flujo_espino,
        lc_query_scope,
        sidebar_badges,
    )
    assert hasattr(sidebar_badges, "conteos_sidebar")
    from demo_web.services import tenant_rules  # noqa: F401
    from demo_web.services import tesoreria_alerta  # noqa: F401

    assert hasattr(tesoreria_alerta, "documentos_por_vencer")

    assert tenant_rules.verify_tenant_registry_errors() == []
    from demo_web.services.native import (  # noqa: F401
        bodega,
        espino,
        espino_bodega,
        espino_libro_campo,
        tesoreria,
    )
    assert hasattr(bodega_kardex, "gather_kardex_producto")
    assert hasattr(espino_scope, "centros_costo_bodega_espino")
    assert hasattr(espino_bodega, "_stock_cc_map")
    from demo_web.services import tenant_scope
    from demo_web.services.espino_scope import prorrateo_pct_espino

    # Esos nombres hacen que app_concepcion impute en partes iguales.
    assert not hasattr(tenant_scope, "ESPINO_CCS")
    assert not hasattr(espino_bodega, "ETIQUETA_BODEGA")
    pct = prorrateo_pct_espino()
    assert abs(sum(pct.values()) - 100.0) < 0.05
    assert pct["SANTINA"] > pct["ROYAL DOWN"] > pct["SWEET ARYANA"]


def _abono_y_saldo() -> None:
    from demo_web.services.native._helpers import parse_decimal_cl, parse_numero_form
    from erp_flujo_financiero import _saldo_pendiente

    assert parse_decimal_cl("850000") == 850_000.0
    assert parse_decimal_cl("1.250.000,50") == 1_250_000.5
    assert parse_decimal_cl("1.5", default=None) is None  # punto decimal rechazado
    # El formulario de bodega usa input type=number, que envía punto decimal.
    assert parse_numero_form("2.5", default=None) == 2.5
    assert parse_numero_form("93488.5", default=None) == 93488.5
    assert parse_numero_form("2,5", default=None) == 2.5
    assert parse_numero_form("1.250.000", default=None) == 1_250_000.0
    assert _saldo_pendiente(1_000_000, 850_000) == 150_000.0
    assert _saldo_pendiente(1_000_000, 1_000_000) == 0.0


def _tesoreria_template_sin_step_mil() -> None:
    html = (ROOT / "demo_web/templates/modules/tesoreria.html").read_text(encoding="utf-8")
    if 'name="monto_abono"' in html:
        assert 'step="1000"' not in html, "monto_abono no debe usar step=1000"
        assert "js-decimal-coma" in html


def main() -> None:
    _imports_criticos()
    _abono_y_saldo()
    _tesoreria_template_sin_step_mil()
    print("OK — smoke_robustez")


if __name__ == "__main__":
    main()
