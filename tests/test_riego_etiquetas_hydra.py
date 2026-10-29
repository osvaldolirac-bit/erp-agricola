"""Riego: HYDRA es una etiqueta con las subetiquetas Riego HYDRA y Config."""
from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from demo_web.services.native.riego import HYDRA_SUB, SECCION_HYDRA, _destino_hydra

ROOT = Path(__file__).resolve().parents[1]


class RiegoEtiquetasHydraTests(unittest.TestCase):
    def test_la_concepcion_tiene_una_etiqueta_y_dos_subetiquetas(self):
        self.assertEqual(SECCION_HYDRA, ("hydra", "💧 HYDRA"))
        self.assertEqual(
            HYDRA_SUB,
            (("riego", "Riego HYDRA"), ("config", "Config")),
        )
        self.assertEqual(_destino_hydra("hydra", ""), ("hydra", "riego"))
        self.assertEqual(_destino_hydra("hydra", "config"), ("hydra", "config"))
        self.assertEqual(_destino_hydra("hydra_config", ""), ("hydra", "config"))
        self.assertEqual(_destino_hydra("manual", ""), ("hydra", "riego"))

        src = (ROOT / "demo_web/services/native/riego.py").read_text()
        self.assertIn("secciones.append(SECCION_HYDRA)", src)
        self.assertNotIn("SECCION_HYDRA_CONFIG", src)
        manual = src.split('elif sec == "manual":', 1)[1].split("elif sec ==", 1)[0]
        self.assertNotIn("contexto_control_hydra_ui", manual)
        hydra = src.split('elif sec == "hydra"', 1)[1].split("return ctx", 1)[0]
        config = hydra.split('if sub == "config":', 1)[1].split("else:", 1)[0]
        riego = hydra.split("else:", 1)[1]
        self.assertNotIn("contexto_control_hydra_ui", config)
        self.assertIn("listar_zonas", config)
        self.assertIn("contexto_control_hydra_ui", riego)
        self.assertIn('ctx["hydra_ui_sub"] = sub', hydra)
        self.assertIn("sub=sub_hydra", src)

    def test_las_plantillas_muestran_subetiquetas(self):
        env = Environment(
            loader=FileSystemLoader(str(ROOT / "demo_web/templates")),
        )
        riego = env.get_template("modules/riego.html")
        html = Path(riego.filename).read_text()
        manual = html.split("{% if sec_activa == 'manual' %}", 1)[1].split(
            "{% elif sec_activa == 'hydra' %}", 1
        )[0]
        app = html.split("{% elif sec_activa == 'hydra' %}", 1)[1].split(
            "{% elif sec_activa == 'bitacora' %}", 1
        )[0]
        self.assertNotIn("_hydra_control_ui", manual)
        self.assertIn("Registro manual", manual)
        self.assertIn("hydra_sub", app)
        self.assertIn("sub_activa == 'riego'", app)
        self.assertIn("_hydra_control_ui.html", app)
        self.assertIn("sub='config'", app)
        self.assertNotIn("hydra_config", html)
        config = (ROOT / "demo_web/templates/partials/riego_hydrawise.html").read_text()
        self.assertIn("sub_activa|default('') == 'config'", config)
        self.assertIn('value="hydra"', config)
        self.assertIn('value="config"', config)
        self.assertIn("sub='riego'", config)
        scope = (ROOT / "demo_web/templates/registro_riego/_hydra_scope_fields.html").read_text()
        self.assertIn("hydra_ui_sub", scope)
        env.get_template("partials/riego_hydrawise.html")
        env.get_template("registro_riego/_hydra_scope_fields.html")


if __name__ == "__main__":
    unittest.main()
