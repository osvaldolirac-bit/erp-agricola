"""Sincronización tenant ↔ constantes LC en módulo compartido."""
from __future__ import annotations

import unittest

from flask import Flask, g

from demo_web.services import erp_loader
from demo_web.services.tenant_scope import centros_costo


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
        variedades = ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"]
        self.assertEqual(erp.CENTROS_COSTO, variedades)
        self.assertEqual(erp.CUARTELES_OFICIALES, variedades)
        self.assertNotIn("Cerezos", erp.CENTROS_COSTO)
        self.assertNotIn("Cerezos", erp.GAP_ESPECIE_CUARTELES["EL ESPINO"])
        self.assertAlmostEqual(sum(erp.PRORRATEO_CC_DEFAULT.values()), 100.0, places=2)
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
        self.assertEqual(
            erp.CENTROS_COSTO, ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"]
        )
        self.assertEqual(erp.LIBRO_CAMPO_ESPECIES, ["Cerezos"])

    def test_gasto_espino_toma_la_variedad_marcada(self):
        erp = _FakeConcepcionErp()
        erp_loader._capture_lc_defaults(erp)
        erp_loader._apply_espino_tenant_overrides(erp)
        app = Flask(__name__)
        with app.test_request_context("/compras"):
            g.tenant_slug = "espino"
            visibles = centros_costo(erp)
            form = {"cc_SANTINA": "1", "cc_Cerezos": "1"}
            selcc = [c for c in visibles if form.get(f"cc_{c}") == "1"]
        self.assertEqual(visibles, ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"])
        self.assertEqual(selcc, ["SANTINA"])


if __name__ == "__main__":
    unittest.main()
