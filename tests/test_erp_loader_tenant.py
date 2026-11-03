"""Sincronización tenant ↔ constantes LC en módulo compartido."""
from __future__ import annotations

import unittest
from unittest import mock

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
        self.assertEqual(erp.CUARTELES_PRORRATEO, variedades)
        self.assertEqual(erp.CUARTELES_IMPUTACION_DIRECTA, [])
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
        self.assertEqual(erp.CUARTELES_IMPUTACION_DIRECTA, ["CIRUELOS"])
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

    def test_cruce_de_listas_no_rechaza_la_variedad_en_espino(self):
        """La reparación de poner la variedad en las dos listas no puede repetir el rechazo."""
        variedades = ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"]

        def clasificar_como_vps(seleccionados):
            sel = [str(c).strip().upper() for c in seleccionados if c]
            directos = [c for c in sel if c in variedades]
            prorr = [c for c in sel if c in variedades]
            invalid = [c for c in sel if c not in directos and c not in prorr]
            return directos, prorr, invalid

        erp = _FakeConcepcionErp()
        erp._clasificar_cc_seleccionados = clasificar_como_vps
        erp_loader._wrap_clasificar_cc_espino(erp)
        erp_loader._wrap_clasificar_cc_espino(erp)
        app = Flask(__name__)
        with app.test_request_context("/rrhh"):
            g.tenant_slug = "espino"
            self.assertEqual(
                erp._clasificar_cc_seleccionados(["SANTINA", "ROYAL DOWN"]),
                ([], ["SANTINA", "ROYAL DOWN"], []),
            )
            self.assertEqual(
                erp._clasificar_cc_seleccionados(["Cerezos"]),
                ([], [], ["CEREZOS"]),
            )
            g.tenant_slug = "concepcion"
            self.assertEqual(
                erp._clasificar_cc_seleccionados(["SANTINA"]),
                (["SANTINA"], ["SANTINA"], []),
            )


class TestDbPorTenant(unittest.TestCase):
    def test_conectar_db_abre_espino_aunque_la_sesion_sea_lc(self):
        erp = _FakeConcepcionErp()
        erp_loader._LC_DEFAULTS = None
        erp_loader._capture_lc_defaults(erp)
        seen: list[str] = []

        def original():
            seen.append(erp.NOMBRE_DB)
            return "ok"

        erp.conectar_db = original
        erp_loader._wrap_conectar_db(erp)
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.tenant_slug = "concepcion"
            token = erp_loader._explicit_db_slug.set("espino")
            try:
                self.assertEqual(erp.conectar_db(), "ok")
            finally:
                erp_loader._explicit_db_slug.reset(token)
            self.assertEqual(seen, ["/root/espino/erp_espino.db"])
            erp.conectar_db()
            self.assertEqual(seen[-1], "/root/erp_concepcion_v6.db")

    def test_lector_de_lc_no_hereda_el_tenant_espino(self):
        opened: list[str | None] = []

        class Conn:
            def close(self):
                return None

        class Erp:
            def conectar_db(self):
                opened.append(erp_loader._explicit_db_slug.get())
                return Conn()

            def usuario_prueba_vigente(self, _fecha):
                return True

            def normalizar_rol_usuario(self, rol, _email):
                return rol

        def bridge(_conn, _email):
            if erp_loader._explicit_db_slug.get() == "concepcion":
                return ("lirac1970@gmail.com", "lector", None)
            return None

        app = Flask(__name__)
        with app.test_request_context("/"):
            g.tenant_slug = "concepcion"
            with mock.patch.object(erp_loader, "get_erp_module_for", return_value=Erp()):
                with mock.patch("demo_web.auth.user_db.fetch_bridge_user", side_effect=bridge):
                    from demo_web.auth.tenant_access import list_accessible_tenants

                    rows = list_accessible_tenants("lirac1970@gmail.com")
        slugs = [r["slug"] for r in rows]
        self.assertEqual(slugs, ["concepcion"])
        self.assertIn("espino", opened)
        self.assertIn("concepcion", opened)


if __name__ == "__main__":
    unittest.main()
