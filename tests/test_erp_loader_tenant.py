"""Sincronización tenant ↔ constantes LC en módulo compartido."""
from __future__ import annotations

import unittest

from demo_web.services import erp_loader


class _FakeConcepcionErp:
    CENTROS_COSTO = ["CIRUELOS", "MANZANOS"]
    CUARTELES_OFICIALES = ["CIRUELOS", "MANZANOS"]
    CUARTELES_PRORRATEO = ["CIRUELOS"]
    CUARTELES_IMPUTACION_DIRECTA = ["CIRUELOS"]
    PRORRATEO_CC_DEFAULT = {"CIRUELOS": 50.0, "MANZANOS": 50.0}
    GAP_ESPECIES = ["Ciruelos"]
    GAP_ESPECIE_CUARTELES = {"Ciruelos": ["CIRUELOS"]}
    LIBRO_CAMPO_ESPECIES = ["Ciruelos"]
    RAZONES_SOCIALES_COMPRAS = ["La Concepción", "El Espino"]
    NOMBRE_DB = "/tmp/lc.db"
    SECRETS_PATH = "/tmp/secrets.toml"
    NOMBRE_ERP = "LC"


class TestLcDefaultsRestore(unittest.TestCase):
    def setUp(self):
        erp_loader._LC_DEFAULTS = None

    def tearDown(self):
        erp_loader._LC_DEFAULTS = None

    def test_espino_override_y_restore_lc(self):
        erp = _FakeConcepcionErp()
        erp_loader._capture_lc_defaults(erp)
        erp_loader._apply_espino_tenant_overrides(erp)
        self.assertEqual(erp.CENTROS_COSTO, ["Cerezos"])
        t_lc = {
            "slug": "concepcion",
            "erp_app": "concepcion",
            "db": "/root/erp_concepcion_v6.db",
            "secrets": "/root/.streamlit/secrets.toml",
            "nombre": "La Concepción",
            "nombre_erp": "ERP Agrícola La Concepción",
        }
        erp_loader._apply_tenant_config(erp, t_lc)
        self.assertEqual(erp.CENTROS_COSTO, ["CIRUELOS", "MANZANOS"])
        self.assertEqual(erp.NOMBRE_DB, "/root/erp_concepcion_v6.db")
        t_esp = {
            "slug": "espino",
            "erp_app": "concepcion",
            "db": "/root/espino/erp_espino.db",
            "secrets": "/root/espino/secrets.toml",
            "nombre": "El Espino",
            "nombre_erp": "ERP Agrícola El Espino",
        }
        erp_loader._apply_tenant_config(erp, t_esp)
        self.assertEqual(erp.NOMBRE_DB, "/root/espino/erp_espino.db")
        self.assertEqual(erp.CENTROS_COSTO, ["Cerezos"])


if __name__ == "__main__":
    unittest.main()
