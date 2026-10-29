"""Riego: registro manual queda solo, e HYDRA se parte en app y configuración."""
from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


class RiegoEtiquetasHydraTests(unittest.TestCase):
    def test_la_concepcion_tiene_app_y_config(self):
        src = (ROOT / "demo_web/services/native/riego.py").read_text()
        self.assertIn('("hydra", "💧 HYDRA RIEGO")', src)
        self.assertIn('("hydra_config", "⚙️ HYDRA CONFIG")', src)
        manual = src.split('elif sec == "manual":', 1)[1].split("elif sec ==", 1)[0]
        self.assertNotIn("contexto_control_hydra_ui", manual)
        app = src.split('elif sec == "hydra"', 1)[1].split("elif sec ==", 1)[0]
        self.assertIn("contexto_control_hydra_ui", app)
        self.assertIn('ctx["hydra_ui_sec"] = "hydra"', app)

    def test_las_plantillas_separan_las_tres_pantallas(self):
        env = Environment(
            loader=FileSystemLoader(str(ROOT / "demo_web/templates")),
        )
        riego = env.get_template("modules/riego.html")
        self.assertIn("sec_activa == 'manual'", riego.filename and Path(riego.filename).read_text())
        html = Path(riego.filename).read_text()
        manual = html.split("{% if sec_activa == 'manual' %}", 1)[1].split("{% elif sec_activa == 'hydra' %}", 1)[0]
        app = html.split("{% elif sec_activa == 'hydra' %}", 1)[1].split("{% elif sec_activa == 'bitacora' %}", 1)[0]
        self.assertNotIn("_hydra_control_ui", manual)
        self.assertIn("Registro manual", manual)
        self.assertIn("_hydra_control_ui.html", app)
        config = (ROOT / "demo_web/templates/partials/riego_hydrawise.html").read_text()
        self.assertIn("sec_activa == 'hydra_config'", config)
        self.assertNotIn('value="hydra"', config.replace('value="hydra_config"', ""))
        self.assertIn("sec='hydra'", config)


if __name__ == "__main__":
    unittest.main()
