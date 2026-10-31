"""Corregir una factura de contratista no la pasa al primer proveedor de la maestra."""
from __future__ import annotations

import unittest
from pathlib import Path

from demo_web.services.native.compras import (
    proveedor_de_correccion,
    proveedores_con_actual,
)


class ComprasProveedorContratistaTests(unittest.TestCase):
    def test_el_contratista_sigue_siendo_el_proveedor(self) -> None:
        self.assertEqual(
            proveedor_de_correccion("ABASTIBLE", "PEDRO QUIÑELAF"),
            "PEDRO QUIÑELAF",
        )

    def test_una_factura_normal_usa_el_formulario(self) -> None:
        self.assertEqual(proveedor_de_correccion("ABASTIBLE", ""), "ABASTIBLE")
        self.assertEqual(proveedor_de_correccion("ABASTIBLE", None), "ABASTIBLE")

    def test_el_selector_incluye_al_contratista(self) -> None:
        maestra = [{"nombre": "ABASTIBLE", "label": "1 · ABASTIBLE"}]
        out = proveedores_con_actual(maestra, "PEDRO QUIÑELAF")
        self.assertEqual(out[0]["nombre"], "PEDRO QUIÑELAF")
        self.assertEqual(out[1]["nombre"], "ABASTIBLE")
        otra = proveedores_con_actual(maestra, "ABASTIBLE")
        self.assertEqual(len(otra), 1)

    def test_el_formulario_fija_al_contratista(self) -> None:
        html = (
            Path(__file__).resolve().parents[1] / "demo_web/templates/modules/compras.html"
        ).read_text(encoding="utf-8")
        self.assertIn("factura_edit.es_contratista", html)
        self.assertIn("Sigue el nombre del contratista", html)


if __name__ == "__main__":
    unittest.main()
