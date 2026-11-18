"""En La Concepción, A mano registra el mismo sector que Hydra."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from demo_web.services.native.riego import _post_manual


def _hydra(sectores, resolver):
    mod = types.ModuleType("demo_web.services.hydrawise_riego")
    mod.sectores_para_link_riego = sectores
    mod.resolver_sector_link = resolver
    return patch.dict(sys.modules, {"demo_web.services.hydrawise_riego": mod})

ROOT = Path(__file__).resolve().parents[1]
SECTOR = {
    "relay_id": 13828796,
    "label": "Sector 4 Nogale — corte 4",
    "huerto_cc": "NOGALES APARICION",
}


class _Demo:
    def hora_chile(self):
        from datetime import datetime

        return datetime(2026, 11, 18, 12, 0, 0)


class TestRiegoManualSectores(unittest.TestCase):
    def test_la_pantalla_ofrece_los_sectores_de_hydra(self):
        html = (ROOT / "demo_web/templates/modules/riego.html").read_text()
        manual = html.split("sec_activa == 'manual'", 1)[1].split("sec_activa == 'hoy'", 1)[0]
        self.assertIn("manual_sectores", manual)
        self.assertIn('name="sector"', manual)
        self.assertIn("{{ s.label }}", manual)
        self.assertIn("Ciruelos", manual)
        self.assertIn("Nogales Cruz del Sur", manual)
        src = (ROOT / "demo_web/services/registro_riego.py").read_text()
        self.assertIn('("CIRUELOS", "Ciruelos")', src)
        self.assertIn('("NOGALES CRUZ DEL SUR", "Nogales Cruz del Sur")', src)
        regar = (ROOT / "demo_web/templates/registro_riego/_hydra_panel_regar.html").read_text()
        self.assertIn("{{ s.label }}", regar)

    def test_el_sector_de_hydra_imputa_su_centro_de_costo(self):
        app = Flask(__name__)
        demo = _Demo()
        data = {
            "fecha": "2026-11-18",
            "relay_id": "13828796",
            "huerto": "CEREZOS CORTE 1",
            "horas": "1",
            "m3": "10",
        }
        registrado = {}

        def _guardar(*args, **kwargs):
            registrado["args"] = args
            registrado["kwargs"] = kwargs
            return {"ok": True, "msg": "ok", "codigo": "RIE-90"}

        with patch(
            "demo_web.services.native.riego.is_concepcion_tenant", return_value=True
        ), _hydra(lambda conn: [SECTOR], lambda conn, rid: SECTOR), patch(
            "demo_web.services.registro_riego.registrar_manual", side_effect=_guardar
        ):
            with app.test_request_context("/", method="POST", data=data):
                res = _post_manual(demo, object(), "osvaldo@laconcepcion.cl")
        self.assertTrue(res["ok"])
        self.assertEqual(registrado["args"][1], "NOGALES APARICION")
        self.assertEqual(registrado["kwargs"]["hydrawise_relay_id"], 13828796)
        self.assertEqual(registrado["kwargs"]["sector_label"], "Sector 4 Nogale — corte 4")

    def test_sin_sector_no_guarda(self):
        app = Flask(__name__)
        with patch(
            "demo_web.services.native.riego.is_concepcion_tenant", return_value=True
        ), _hydra(lambda conn: [SECTOR], lambda conn, rid: None), patch(
            "demo_web.services.registro_riego.registrar_manual"
        ) as guardar:
            with app.test_request_context("/", method="POST", data={"relay_id": "0"}):
                res = _post_manual(_Demo(), object(), "osvaldo@laconcepcion.cl")
        self.assertFalse(res["ok"])
        self.assertIn("sector", res["msg"].lower())
        guardar.assert_not_called()

    def test_ciruelos_y_cruz_del_sur_se_imputan_a_su_huerto(self):
        app = Flask(__name__)
        casos = (
            ("cc:CIRUELOS", "CIRUELOS", "Ciruelos"),
            ("cc:NOGALES CRUZ DEL SUR", "NOGALES CRUZ DEL SUR", "Nogales Cruz del Sur"),
        )
        for valor, cc, label in casos:
            registrado = {}

            def _guardar(*args, **kwargs):
                registrado["args"] = args
                registrado["kwargs"] = kwargs
                return {"ok": True, "msg": "ok", "codigo": "RIE-91"}

            with patch(
                "demo_web.services.native.riego.is_concepcion_tenant", return_value=True
            ), _hydra(lambda conn: [SECTOR], lambda conn, rid: SECTOR), patch(
                "demo_web.services.registro_riego.registrar_manual", side_effect=_guardar
            ):
                with app.test_request_context("/", method="POST", data={"sector": valor, "fecha": "2026-11-18", "horas": "1", "m3": "5"}):
                    res = _post_manual(_Demo(), object(), "osvaldo@laconcepcion.cl")
            self.assertTrue(res["ok"], valor)
            self.assertEqual(registrado["args"][1], cc)
            self.assertIsNone(registrado["kwargs"]["hydrawise_relay_id"])
            self.assertEqual(registrado["kwargs"]["sector_label"], label)
