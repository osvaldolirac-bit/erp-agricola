"""El módulo EL ESPINO del menú es de La Concepción."""
from __future__ import annotations

import unittest

from demo_web.auth.decorators import modulo_visible_en_tenant


class TestModuloEspinoSoloLc(unittest.TestCase):
    def test_el_espino_no_aparece_en_su_propio_tenant(self):
        self.assertFalse(modulo_visible_en_tenant("Espino", "espino"))
        self.assertFalse(modulo_visible_en_tenant("Espino", "demo"))

    def test_la_concepcion_conserva_el_modulo(self):
        self.assertTrue(modulo_visible_en_tenant("Espino", "concepcion"))

    def test_el_resto_del_menu_sigue_en_espino(self):
        for key in ("DASHBOARD", "Compras", "Bodega", "RRHH", "Libro de Campo"):
            self.assertTrue(modulo_visible_en_tenant(key, "espino"))
