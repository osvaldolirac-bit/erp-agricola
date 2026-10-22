"""La Concepción: la pestaña Hydrawise y el CSS del link no se pierden en el deploy."""
from __future__ import annotations

import unittest
from pathlib import Path

from flask import Flask, g

from demo_web.services.native.administracion import SECCION_DEFS, _secciones_visibles

ROOT = Path(__file__).resolve().parents[1]


class _Demo:
    def es_super_admin(self):
        return False


class TestLcHydraEnlace(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _secciones(self, slug: str) -> list[str]:
        with self.app.test_request_context("/admin"):
            g.tenant_slug = slug
            return [key for key, _label in _secciones_visibles(_Demo())]

    def test_pestaña_hydrawise_solo_en_la_concepcion(self):
        self.assertIn(("hydrawise", "💧 HYDRAWISE", "lc"), SECCION_DEFS)
        self.assertIn("hydrawise", self._secciones("concepcion"))
        self.assertNotIn("hydrawise", self._secciones("espino"))
        self.assertNotIn("hydrawise", self._secciones("demo"))

    def test_css_del_link_regador_sigue_en_el_manifest(self):
        css = (ROOT / "demo_web/static/css/erp.css").read_text()
        for selector in (
            ".hydra-link-page",
            ".hydra-link-tabs",
            ".hydra-link-tab.is-active",
            ".hydra-conn-witness--ok",
            ".hydra-zone-grid",
        ):
            self.assertIn(selector, css, selector)
        html = (ROOT / "demo_web/templates/modules/administracion.html").read_text()
        self.assertIn("sec_activa == 'hydrawise'", html)
        self.assertIn("guardar_hydrawise_key", html)
