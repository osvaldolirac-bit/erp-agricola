"""Registro tenants LC + reglas."""
from __future__ import annotations

import unittest

from demo_web.services.tenant_rules import (
    CONCEPCION,
    ESPINO,
    LC_TENANT_SLUGS,
    rules_for_slug,
    verify_tenant_registry_errors,
)


class TestTenantRegistry(unittest.TestCase):
    def test_lc_slugs_rules(self) -> None:
        self.assertTrue(CONCEPCION.excluir_razon_social_el_espino)
        self.assertFalse(ESPINO.excluir_razon_social_el_espino)
        self.assertEqual(rules_for_slug("concepcion"), CONCEPCION)

    def test_registry_ok(self) -> None:
        self.assertEqual(verify_tenant_registry_errors(), [])
        self.assertIn("concepcion", LC_TENANT_SLUGS)
        self.assertIn("espino", LC_TENANT_SLUGS)


if __name__ == "__main__":
    unittest.main()
