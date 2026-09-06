#!/usr/bin/env python3
"""Tests reglas centralizadas tenant_rules.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TenantRulesModuleTest(unittest.TestCase):
    def test_matriz_concepcion(self) -> None:
        from demo_web.services.tenant_rules import CONCEPCION

        self.assertTrue(CONCEPCION.cxp_saldo_neto)
        self.assertFalse(CONCEPCION.cxp_incluye_documentos_int)
        self.assertTrue(CONCEPCION.excluir_razon_social_el_espino)
        self.assertFalse(CONCEPCION.flujo_imputar_gastado_contable)

    def test_matriz_espino(self) -> None:
        from demo_web.services.tenant_rules import ESPINO

        self.assertFalse(ESPINO.cxp_saldo_neto)
        self.assertTrue(ESPINO.cxp_incluye_documentos_int)
        self.assertFalse(ESPINO.excluir_razon_social_el_espino)
        self.assertTrue(ESPINO.flujo_imputar_gastado_contable)

    def test_verify_implementation_clean(self) -> None:
        from demo_web.services.tenant_rules import verify_implementation_errors

        errors = verify_implementation_errors()
        self.assertEqual(errors, [], msg="\n".join(errors))

    def test_cxp_helpers_espino(self) -> None:
        from demo_web.services.tenant_rules import cxp_incluye_documentos_int, cxp_usar_saldo_neto

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="espino"):
            self.assertFalse(cxp_usar_saldo_neto())
            self.assertTrue(cxp_incluye_documentos_int())

    def test_cxp_helpers_lc(self) -> None:
        from demo_web.services.tenant_rules import cxp_incluye_documentos_int, cxp_usar_saldo_neto

        with patch("demo_web.services.tenant_scope.tenant_slug", return_value="concepcion"):
            self.assertTrue(cxp_usar_saldo_neto())
            self.assertFalse(cxp_incluye_documentos_int())


if __name__ == "__main__":
    raise SystemExit(unittest.main())
