#!/usr/bin/env python3
"""Tests unitarios reglas tenant Espino vs LC (sin VPS)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class EspinoTenantRulesTest(unittest.TestCase):
    def test_espino_no_usa_saldo_neto(self) -> None:
        from demo_web.services.tesoreria_cxp import (
            saldo_factura_tesoreria,
            usar_saldo_cxp_neto_en_tesoreria,
        )

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="espino"):
            self.assertFalse(usar_saldo_cxp_neto_en_tesoreria())
            self.assertAlmostEqual(saldo_factura_tesoreria(500, 100, 300), 400.0)

    def test_lc_usa_saldo_neto(self) -> None:
        from demo_web.services.tesoreria_cxp import saldo_factura_tesoreria

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
            self.assertAlmostEqual(saldo_factura_tesoreria(500, 100, 300), 100.0)

    def test_lc_pago_usa_saldo_bruto_aun_imputado(self) -> None:
        from demo_web.services.tesoreria_cxp import saldo_factura_para_pago, saldo_factura_tesoreria

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
            self.assertAlmostEqual(saldo_factura_tesoreria(443500, 0, 443500), 0.0)
            self.assertAlmostEqual(saldo_factura_para_pago(443500, 0, 443500), 443500.0)

    def test_espino_incluye_int_en_sql(self) -> None:
        from demo_web.services.tesoreria_cxp import sql_solo_cxp_tesoreria

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="espino"):
            sql = sql_solo_cxp_tesoreria("f")
            self.assertNotIn("INT-*", sql)

    def test_lc_excluye_int_en_sql(self) -> None:
        from demo_web.services.tesoreria_cxp import sql_solo_cxp_tesoreria

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
            sql = sql_solo_cxp_tesoreria("f")
            self.assertIn("INT-*", sql)

    def test_lc_excluye_razon_espino_no_espino(self) -> None:
        from demo_web.services.lc_excluir_espino import sql_and_excluir_razon_social_espino

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
            sql = sql_and_excluir_razon_social_espino(alias="f")
            self.assertIn("El Espino", sql)

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="espino"):
            self.assertEqual(sql_and_excluir_razon_social_espino(alias="f"), "")

    def test_espino_muestra_master_brand(self) -> None:
        from demo_web.services.branding import tenant_shows_master_brand

        self.assertTrue(tenant_shows_master_brand("espino"))
        self.assertTrue(tenant_shows_master_brand("concepcion"))
        self.assertFalse(tenant_shows_master_brand("demo"))
        self.assertFalse(tenant_shows_master_brand("globalgap"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
