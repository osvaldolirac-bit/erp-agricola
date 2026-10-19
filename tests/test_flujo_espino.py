"""Ingresos flujo Espino: prorrateo legacy Cerezos."""
from __future__ import annotations

import unittest

from demo_web.services.flujo_espino import normalizar_mapa_ingresos_cc


class TestFlujoEspino(unittest.TestCase):
    def test_cerezos_prorratea_en_variedades(self):
        cuarteles = ["ROYAL DOWN", "SWEET ARYANA", "SANTINA"]
        ing = {("Cerezos", 2026, 7): 100.0}
        out = normalizar_mapa_ingresos_cc(ing, cuarteles)
        self.assertNotIn(("Cerezos", 2026, 7), out)
        total = sum(out.values())
        self.assertAlmostEqual(total, 100.0, places=2)
        self.assertEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
