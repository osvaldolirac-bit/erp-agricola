"""Compras → Insumos bodega muestra y guarda el ingrediente activo."""
from __future__ import annotations

import unittest
from pathlib import Path

from demo_web.services.native.compras import etiqueta_insumo_bodega

ROOT = Path(__file__).resolve().parents[1]


class TestEtiquetaInsumo(unittest.TestCase):
    def test_incluye_el_ingrediente(self):
        self.assertEqual(
            etiqueta_insumo_bodega("EXIREL", "lt", "Cyantraniliprole"),
            "EXIREL — Cyantraniliprole (lt)",
        )

    def test_sin_ingrediente_queda_nombre_y_unidad(self):
        self.assertEqual(etiqueta_insumo_bodega("UREA", "kg", "  "), "UREA (kg)")


class TestFormularioInsumos(unittest.TestCase):
    def test_el_producto_nuevo_pide_ingrediente(self):
        html = (ROOT / "demo_web/templates/modules/compras.html").read_text(encoding="utf-8")
        nuevo = html.split('id="blkNuevo"', 1)[1].split('name="cantidad"', 1)[0]
        self.assertIn('name="ingrediente_activo"', nuevo)
        self.assertIn('id="ingredienteActivo"', nuevo)
        self.assertIn("Ing. activo", html)
        self.assertIn("syncIngredienteActivo", html)

    def test_la_compra_guarda_el_ingrediente_escrito(self):
        src = (ROOT / "demo_web/services/native/compras.py").read_text(encoding="utf-8")
        self.assertIn('if nia:\n            item["ingrediente_activo"] = nia', src)
        self.assertIn("guardar_ingrediente_producto(conn, new_id, nia)", src)
        self.assertIn("COALESCE(ingrediente_activo, '')", src)
