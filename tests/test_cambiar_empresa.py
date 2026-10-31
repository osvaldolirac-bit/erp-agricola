"""Cambiar empresa vuelve al navbar y el deploy no sale sin ese botón."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CambiarEmpresaTests(unittest.TestCase):
    def test_navbar_y_contexto(self) -> None:
        base = (ROOT / "demo_web/templates/base.html").read_text(encoding="utf-8")
        css = (ROOT / "demo_web/static/css/erp.css").read_text(encoding="utf-8")
        app = (ROOT / "demo_web/app.py").read_text(encoding="utf-8")
        routes = (ROOT / "demo_web/auth/routes.py").read_text(encoding="utf-8")
        self.assertIn("Cambiar empresa", base)
        self.assertIn("auth.cambiar_empresa", base)
        self.assertIn("tenant_switch_options", base)
        self.assertIn(".demo-tenant-switch-btn", css)
        self.assertIn("tenant_switch_options", app)
        self.assertIn("other_tenant_switch_options", app)
        self.assertIn("def cambiar_empresa", routes)

    def test_deploy_es_un_paquete(self) -> None:
        script = (ROOT / "scripts/deploy_robustez_lc_espino_vps.py").read_text(encoding="utf-8")
        self.assertIn("demo_web/app.py", script)
        self.assertIn("demo_web/templates/base.html", script)
        self.assertIn("assert_cambiar_empresa", script)
        self.assertIn('"-czf"', script)
        self.assertNotIn("for rel in ROBUSTEZ_LC_ESPINO_FILES:", script)


if __name__ == "__main__":
    unittest.main()
