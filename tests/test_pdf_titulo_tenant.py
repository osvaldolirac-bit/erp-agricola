"""El Espino no hereda el título de archivo de La Concepción."""
from __future__ import annotations

import unittest
from pathlib import Path

from flask import Flask, g

from demo_web.services.pdf_meta import marca_corta_pdf, nombre_archivo_segun_tenant

ROOT = Path(__file__).resolve().parents[1]


class PdfTituloTenantTests(unittest.TestCase):
    def test_espino_cambia_el_nombre(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.tenant_slug = "espino"
            self.assertEqual(marca_corta_pdf(), "EL ESPINO")
            self.assertEqual(
                nombre_archivo_segun_tenant("LIBRO_DE_CAMPO_LA_CONCEPCION.pdf"),
                "LIBRO_DE_CAMPO_EL_ESPINO.pdf",
            )
            self.assertEqual(
                nombre_archivo_segun_tenant("historial_compras.pdf"),
                "historial_compras.pdf",
            )

    def test_la_concepcion_conserva_el_nombre(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.tenant_slug = "concepcion"
            self.assertEqual(marca_corta_pdf(), "LA CONCEPCION")
            self.assertEqual(
                nombre_archivo_segun_tenant("LIBRO_DE_CAMPO_LA_CONCEPCION.pdf"),
                "LIBRO_DE_CAMPO_LA_CONCEPCION.pdf",
            )

    def test_libro_y_el_visor_usan_el_nombre_del_tenant(self) -> None:
        libro = (ROOT / "demo_web/services/native/libro_campo.py").read_text(encoding="utf-8")
        runner = (ROOT / "demo_web/services/module_runner.py").read_text(encoding="utf-8")
        plantilla = (ROOT / "demo_web/templates/modules/libro_campo.html").read_text(encoding="utf-8")
        manifest = (ROOT / "scripts/deploy_robustez_lc_espino_vps.py").read_text(encoding="utf-8")
        self.assertIn("nombre_archivo_segun_tenant", libro)
        self.assertIn("titulo_pdf", libro)
        self.assertIn("rebaje_bodega_al_guardar", libro)
        self.assertIn('== "espino" or is_concepcion_tenant()', libro)
        ingreso = plantilla.split("sec_activa == 'ingreso'", 1)[1]
        aviso, resto = ingreso.split("{% else %}", 1)
        self.assertIn("rebaje_bodega_al_guardar", aviso)
        self.assertIn("rebaja el stock", aviso)
        self.assertNotIn("módulos independientes", aviso)
        self.assertIn("módulos independientes", resto.split("{% endif %}", 1)[0])
        self.assertIn("nombre_archivo_segun_tenant", runner)
        self.assertNotIn("LIBRO_DE_CAMPO_LA_CONCEPCION.pdf", plantilla)
        self.assertNotIn("Copiar a ingreso", plantilla)
        self.assertNotIn("copiar_aplicacion_ingreso", libro)
        self.assertNotIn("lc_copiado_desde_n_app", libro)
        self.assertIn("demo_web/services/pdf_meta.py", manifest)
        self.assertIn("demo_web/services/module_runner.py", manifest)
        self.assertIn("demo_web/templates/modules/libro_campo.html", manifest)


if __name__ == "__main__":
    unittest.main()
