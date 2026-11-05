"""Un segundo «regar» no abre otra cola si el corte ya tiene orden."""
from __future__ import annotations

import sqlite3
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

# erp_solo_lectura vive en el VPS. En el test la base es escribible.
if "erp_solo_lectura" not in sys.modules:
    _solo = types.ModuleType("erp_solo_lectura")
    _solo.conn_en_solo_lectura = lambda conn: False
    sys.modules["erp_solo_lectura"] = _solo

# El cliente HTTP de Hydrawise vive en el VPS y no está en este árbol.
if "demo_web.services.hydrawise_client" not in sys.modules:
    _cliente = types.ModuleType("demo_web.services.hydrawise_client")
    for _nombre in (
        "customer_details",
        "flatten_relays",
        "flatten_relays_from_status",
        "last_contact_from_customer",
        "list_controllers",
        "relay_status_map",
        "set_zone_run",
        "set_zone_stop_all",
        "status_schedule",
    ):
        setattr(_cliente, _nombre, lambda *a, **k: None)
    sys.modules["demo_web.services.hydrawise_client"] = _cliente

from demo_web.services.hydrawise_riego import crear_cola, migrar_hydrawise


class _Reloj:
    def hora_chile(self):
        return datetime(2026, 11, 5, 8, 1, 10)


class TestDobleOrdenRiego(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        migrar_hydrawise(self.conn)
        self.conn.execute(
            """CREATE TABLE inventario (
                   id INTEGER PRIMARY KEY,
                   producto TEXT,
                   familia TEXT
               )"""
        )
        self.conn.executemany(
            """INSERT INTO hydrawise_zona
               (relay_id, nombre_hw, alias, huerto_cc, modo_riego, activo, link_riego)
               VALUES (?, ?, ?, ?, 'horas', 1, 1)""",
            [
                (13828789, "Sector 2 cerezo", "corte 2", "CEREZOS CORTE 2"),
                (13828764, "Sector 1 cerezo", "corte 1", "CEREZOS CORTE 1"),
            ],
        )
        self.conn.commit()
        self.patches = [
            patch(
                "demo_web.services.hydrawise_riego.get_demo_module",
                return_value=_Reloj(),
            ),
            patch(
                "demo_web.services.registro_riego.enviar_alerta_hydra_cola_inicio",
                return_value=False,
            ),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _ordenar(self, relay: int):
        return crear_cola(
            self.conn,
            tipo="run_now",
            inicio_programa="2026-11-05 08:01:10",
            lineas=[{"relay_id": relay, "minutos": 120, "fertilizantes": []}],
            usuario="Pablo Acevedo Becerra",
        )

    def _n_colas(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM hydrawise_cola").fetchone()[0])

    def test_el_mismo_corte_pendiente_no_abre_otra_cola(self):
        primero = self._ordenar(13828789)
        self.assertTrue(primero["ok"], primero)
        segundo = self._ordenar(13828789)
        self.assertFalse(segundo["ok"])
        self.assertIn("ya tiene una orden de riego", segundo["msg"])
        self.assertEqual(self._n_colas(), 1)
        estados = [
            r[0]
            for r in self.conn.execute(
                "SELECT estado FROM hydrawise_cola_item WHERE relay_id=?",
                (13828789,),
            )
        ]
        self.assertEqual(estados, ["pendiente"])

    def test_otro_corte_tampoco_parte_mientras_hay_orden(self):
        primero = self._ordenar(13828789)
        self.assertTrue(primero["ok"], primero)
        otro = self._ordenar(13828764)
        self.assertFalse(otro["ok"])
        self.assertIn("orden de riego en curso", otro["msg"])
        self.assertEqual(self._n_colas(), 1)

    def test_corte_corriendo_sigue_bloqueado(self):
        primero = self._ordenar(13828789)
        self.assertTrue(primero["ok"], primero)
        self.conn.execute(
            "UPDATE hydrawise_cola SET estado='en_ejecucion' WHERE id=?",
            (primero["cola_id"],),
        )
        self.conn.execute(
            """UPDATE hydrawise_cola_item
               SET estado='corriendo', run_inicio='2026-11-05 08:01:14'
               WHERE cola_id=?""",
            (primero["cola_id"],),
        )
        self.conn.commit()
        segundo = self._ordenar(13828789)
        self.assertFalse(segundo["ok"])
        self.assertEqual(self._n_colas(), 1)

    def test_al_terminar_la_orden_se_puede_regar_de_nuevo(self):
        primero = self._ordenar(13828789)
        self.conn.execute(
            "UPDATE hydrawise_cola SET estado='completado' WHERE id=?",
            (primero["cola_id"],),
        )
        self.conn.execute(
            "UPDATE hydrawise_cola_item SET estado='importado' WHERE cola_id=?",
            (primero["cola_id"],),
        )
        self.conn.commit()
        otra = self._ordenar(13828789)
        self.assertTrue(otra["ok"], otra)
        self.assertEqual(self._n_colas(), 2)
