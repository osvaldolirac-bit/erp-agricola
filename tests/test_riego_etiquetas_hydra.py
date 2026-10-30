"""Riego LC: Hoy, Regar, Historial y Armado. El Espino conserva su barra."""
from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from demo_web.services.native.riego import (
    ARMADO_SUB,
    REGAR_SUB,
    SECCIONES,
    SECCIONES_LC,
    _canon_lc,
    _canon_post_hydra,
)

ROOT = Path(__file__).resolve().parents[1]


class RiegoOficinaLcTests(unittest.TestCase):
    def test_la_concepcion_tiene_cuatro_etiquetas(self):
        self.assertEqual(
            SECCIONES_LC,
            [
                ("hoy", "Hoy"),
                ("regar", "Regar"),
                ("historial", "Historial"),
                ("armado", "Armado"),
            ],
        )
        self.assertEqual(REGAR_SUB, (("ahora", "Ahora"), ("programar", "Programar")))
        self.assertEqual(
            ARMADO_SUB,
            (
                ("sectores", "Sectores"),
                ("enlaces", "Enlaces"),
                ("parametros", "Parámetros"),
                ("manual", "A mano"),
            ),
        )
        self.assertEqual(
            SECCIONES,
            [
                ("historial", "📊 HISTORIAL"),
                ("manual", "✏️ REGISTRO MANUAL"),
                ("bitacora", "🔗 LINK RIEGO"),
            ],
        )
        self.assertEqual(_canon_lc("hydra", ""), ("hoy", ""))
        self.assertEqual(_canon_lc("hydra", "riego"), ("hoy", ""))
        self.assertEqual(_canon_lc("hydra", "config"), ("armado", "sectores"))
        self.assertEqual(_canon_lc("hydra_config", ""), ("armado", "sectores"))
        self.assertEqual(_canon_lc("manual", ""), ("armado", "manual"))
        self.assertEqual(_canon_lc("bitacora", ""), ("hoy", ""))
        self.assertEqual(_canon_lc("regar", ""), ("regar", "ahora"))
        self.assertEqual(_canon_lc("regar", "programar"), ("regar", "programar"))
        self.assertEqual(_canon_lc("armado", ""), ("armado", "sectores"))
        self.assertEqual(_canon_lc("armado", "enlaces"), ("armado", "enlaces"))
        self.assertEqual(_canon_lc("hoy", "ahora"), ("hoy", ""))
        self.assertEqual(_canon_lc("historial", "x"), ("historial", ""))
        self.assertEqual(_canon_lc("", ""), ("historial", ""))
        self.assertEqual(_canon_post_hydra("manual", ""), ("hoy", ""))
        self.assertEqual(_canon_post_hydra("regar", "programar"), ("regar", "programar"))
        self.assertEqual(_canon_post_hydra("hoy", ""), ("hoy", ""))
        self.assertEqual(_canon_post_hydra("armado", "sectores"), ("armado", "sectores"))

        src = (ROOT / "demo_web/services/native/riego.py").read_text()
        self.assertIn("SECCIONES_LC", src)
        self.assertNotIn("SECCION_HYDRA", src)
        manual = src.split('elif sec == "manual":', 1)[1].split("return ctx", 1)[0]
        self.assertNotIn("contexto_control_hydra_ui", manual)
        hoy = src.split('elif sec == "hoy":', 1)[1].split("elif sec ==", 1)[0]
        regar = src.split('elif sec == "regar":', 1)[1].split("elif sec ==", 1)[0]
        sectores = src.split('sub == "sectores"', 1)[1].split("elif sec ==", 1)[0]
        self.assertIn("contexto_control_hydra_ui", hoy)
        self.assertIn("auto_sync=True", hoy)
        self.assertIn("auto_sync=False", regar)
        self.assertNotIn("auto_sync=True", regar)
        self.assertIn("listar_zonas", sectores)
        self.assertNotIn("contexto_control_hydra_ui", sectores)
        self.assertIn('return _volver("hoy")', src)
        self.assertIn('return _volver("armado", "manual")', src)
        self.assertIn('return _volver("bitacora")', src)

    def test_las_plantillas_separan_hoy_regar_y_armado(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / "demo_web/templates")))
        riego = env.get_template("modules/riego.html")
        html = Path(riego.filename).read_text()
        self.assertIn("sec_activa == 'hoy'", html)
        self.assertIn("sec_activa == 'regar'", html)
        self.assertIn("sec_activa == 'armado'", html)
        self.assertIn("sec_activa == 'manual'", html)
        self.assertIn("sec_activa == 'bitacora'", html)
        self.assertIn("sec_activa == 'historial'", html)
        self.assertNotIn("sec_activa == 'hydra'", html)
        self.assertNotIn("hydra_config", html)
        self.assertIn("Para autorizar", html)
        self.assertIn("sub='ahora'", html)
        self.assertIn("sub='sectores'", html)
        self.assertIn("Registro manual", html)
        manual = html.split("sec_activa == 'manual'", 1)[1].split("sec_activa == 'hoy'", 1)[0]
        self.assertNotIn("_hydra_control_ui", manual)
        control = (ROOT / "demo_web/templates/registro_riego/_hydra_control_ui.html").read_text()
        self.assertIn("Actualizar con Hydrawise", control)
        self.assertIn("vista == 'hoy'", control)
        self.assertIn("vista == 'ahora'", control)
        self.assertIn("vista == 'programar'", control)
        config = (ROOT / "demo_web/templates/partials/riego_hydrawise.html").read_text()
        self.assertIn("sub_activa|default('') == 'sectores'", config)
        self.assertIn('value="armado"', config)
        self.assertIn('value="sectores"', config)
        self.assertIn("sec='hoy'", config)
        self.assertNotIn('value="hydra"', config)
        phone = (ROOT / "demo_web/templates/registro_riego/hydra_link.html").read_text()
        self.assertNotIn("Actualizar con Hydrawise", phone)
        env.get_template("partials/riego_hydrawise.html")
        env.get_template("partials/riego_tabla_autorizar.html")
        env.get_template("partials/riego_enlaces.html")
        env.get_template("partials/riego_parametros.html")
        env.get_template("registro_riego/_hydra_control_ui.html")


if __name__ == "__main__":
    unittest.main()
