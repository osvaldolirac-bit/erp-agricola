"""El enlace de bodega busca igual que el módulo Bodega."""
from __future__ import annotations

import unittest

from demo_web.services.native.bodega_stock_rapido import coincide_busqueda


class TestFiltroEnlaceBodega(unittest.TestCase):
    def test_vacio_muestra_el_producto(self):
        self.assertTrue(coincide_busqueda("", "UREA", "FERTILIZANTE", "Nitrógeno"))

    def test_nombre(self):
        self.assertTrue(coincide_busqueda("urea", "UREA", "FERTILIZANTE", "Nitrógeno"))
        self.assertFalse(coincide_busqueda("urea", "AFFINITY", "HERBICIDA", "Glifosato"))

    def test_familia_aunque_el_nombre_no_la_traiga(self):
        self.assertTrue(coincide_busqueda("fungicida", "ADMIRAL", "FUNGICIDA", "Piriproxifen"))
        self.assertTrue(coincide_busqueda("Fertilizante foliar", "AGROMIL", "FERTILIZANTE FOLIAR", "Calcio"))

    def test_ingrediente_activo_aunque_el_nombre_no_lo_traiga(self):
        self.assertTrue(coincide_busqueda("glifosato", "AFFINITY", "HERBICIDA", "Glifosato"))
        self.assertTrue(coincide_busqueda("piriproxifen", "ADMIRAL", "INSECTICIDA", "Piriproxifen"))
        self.assertFalse(coincide_busqueda("glifosato", "UREA", "FERTILIZANTE", "Nitrógeno"))


if __name__ == "__main__":
    unittest.main()
