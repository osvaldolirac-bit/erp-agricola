"""Regar ahora no se cae al leer el ítem que trae fert_json."""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from demo_web.services.hydrawise_cola_item import ficha_zona_corriendo, partes_item


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
        self.assertIn("ejecucion_por_relay", texto)

    def test_la_zona_corriendo_arma_la_ficha_del_detalle(self):
        ahora = datetime(2026, 10, 28, 8, 30, 26)
        ficha = ficha_zona_corriendo(
            label="Sector 1 Cerezo — corte 1",
            huerto_cc="CEREZOS CORTE 1",
            cola_id=12,
            tipo="run_now",
            inicio_programa="2026-10-28 07:52:19",
            creado_por="Regador",
            minutos=120,
            run_inicio="2026-10-28 08:00:26",
            fertilizantes=[
                {"nombre": "Nitrato", "cantidad_fmt": "2 kg", "dosis_fmt": "10 / ha"}
            ],
            ahora=ahora,
        )
        self.assertEqual(ficha["tipo_label"], "Regar ahora")
        self.assertEqual(ficha["huerto_cc"], "CEREZOS CORTE 1")
        self.assertEqual(ficha["cola_id"], 12)
        self.assertEqual(ficha["run_inicio_fmt"], "28/10/2026 08:00")
        self.assertEqual(ficha["fin_estimado_fmt"], "28/10/2026 10:00")
        self.assertEqual(ficha["minutos_fmt"], "2 h")
        self.assertEqual(ficha["remaining_sec"], 90 * 60)
        self.assertEqual(ficha["remaining_clock"], "1:30:00")
        self.assertEqual(ficha["remaining_fmt"], "1 h 30 min")
        self.assertTrue(ficha["tiene_fertirriego"])
        self.assertEqual(ficha["fertilizantes"][0]["nombre"], "Nitrato")
        panel = Path(
            "demo_web/templates/registro_riego/_hydra_panel_control.html"
        ).read_text(encoding="utf-8")
        self.assertIn("hydra-zone-card--tappable", panel)
        self.assertIn("hydraEjecucionJson", panel)
        self.assertIn("Toque para ver el detalle", panel)
        oficina = Path(
            "demo_web/templates/registro_riego/_hydra_control_ui.html"
        ).read_text(encoding="utf-8")
        self.assertIn("hydra_link_running_detail.js", oficina)
        self.assertIn("_hydra_running_detail_modal.html", oficina)
