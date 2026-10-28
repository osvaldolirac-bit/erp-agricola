"""Regar ahora no se cae al leer el ítem que trae fert_json."""
from __future__ import annotations

import unittest
from pathlib import Path

from demo_web.services.hydrawise_cola_item import partes_item


class TestItemColaHydra(unittest.TestCase):
    def test_la_fila_con_fert_json_se_lee_completa(self):
        fila = (7, 1, 13828764, 120.0, "pendiente", "", "", "", "", "[]")
        item_id, _, relay_id, minutos, estado, *_resto = partes_item(fila)
        self.assertEqual(item_id, 7)
        self.assertEqual(relay_id, 13828764)
        self.assertEqual(minutos, 120.0)
        self.assertEqual(estado, "pendiente")
        self.assertEqual(len(partes_item(fila)), 10)
        self.assertEqual(partes_item(fila)[-1], "[]")

    def test_el_arranque_usa_las_diez_columnas(self):
        texto = Path("demo_web/services/hydrawise_riego.py").read_text(encoding="utf-8")
        self.assertIn("partes_item(pending)", texto)
        self.assertIn("partes_item(running_item)", texto)
        self.assertNotIn("_, _, _, _ = pending", texto)
        self.assertIn("COALESCE(fert_json, '')", texto)
