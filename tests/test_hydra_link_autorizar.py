"""Los riegos HYDRA de hoy quedan en Link riego para autorizar."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from demo_web.services.registro_riego import reencolar_hydra_sin_autorizar

ROOT = Path(__file__).resolve().parents[1]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE riego (
            id INTEGER PRIMARY KEY,
            codigo TEXT UNIQUE,
            fecha TEXT,
            huerto TEXT,
            horas REAL,
            m3 REAL,
            fert_dosis_ha REAL,
            fert_total REAL,
            regador TEXT,
            origen TEXT,
            creado_en TEXT,
            modo_riego TEXT,
            surcos REAL,
            fert_estado TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE riego_bitacora (
            id INTEGER PRIMARY KEY,
            codigo TEXT UNIQUE,
            fecha TEXT,
            huerto TEXT,
            horas REAL,
            m3 REAL,
            fert_dosis_ha REAL,
            fert_total REAL,
            regador TEXT,
            creado_en TEXT,
            estado TEXT,
            modo_riego TEXT,
            surcos REAL,
            hydrawise_relay_id INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE hydrawise_cola_item (
            id INTEGER PRIMARY KEY,
            codigo_riego TEXT,
            relay_id INTEGER
        )"""
    )
    return conn


class TestReencolarHydra(unittest.TestCase):
    def test_el_riego_de_hoy_pasa_a_link_y_no_se_duplica(self):
        conn = _conn()
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, fert_total, regador, origen, creado_en, modo_riego, fert_estado)
               VALUES ('RIE-22', '2026-10-28', 'NOGALES APARICION', 1.5, 357, 18, 'Pablo', 'hydrawise',
                       '2026-10-28 15:08:08', 'horas', 'pendiente')"""
        )
        conn.execute(
            "INSERT INTO hydrawise_cola_item (codigo_riego, relay_id) VALUES ('RIE-22', 99)"
        )
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, regador, origen, creado_en, fert_estado)
               VALUES ('RIE-10', '2026-10-15', 'CEREZOS CORTE 1', 1, 10, 'Pablo', 'hydrawise',
                       '2026-10-15 10:00:00', 'confirmado')"""
        )
        n = reencolar_hydra_sin_autorizar(conn)
        self.assertEqual(n, 1)
        pendiente = conn.execute(
            "SELECT estado, hydrawise_relay_id, huerto FROM riego_bitacora WHERE codigo='RIE-22'"
        ).fetchone()
        self.assertEqual(pendiente, ("pendiente", 99, "NOGALES APARICION"))
        self.assertIsNone(
            conn.execute("SELECT 1 FROM riego WHERE codigo='RIE-22'").fetchone()
        )
        self.assertIsNotNone(
            conn.execute("SELECT 1 FROM riego WHERE codigo='RIE-10'").fetchone()
        )
        self.assertEqual(reencolar_hydra_sin_autorizar(conn), 0)

    def test_el_alta_de_hydra_queda_en_la_bitacora_del_link(self):
        src = (ROOT / "demo_web/services/registro_riego.py").read_text(encoding="utf-8")
        bloque = src.split("def registrar_desde_hydrawise", 1)[1].split("\ndef habilitado", 1)[0]
        self.assertIn("INSERT INTO riego_bitacora", bloque)
        self.assertNotIn("INSERT INTO riego\n", bloque)
        self.assertNotIn("INSERT INTO riego ", bloque)
        self.assertIn("pendiente de autorizar", bloque)
        riego = (ROOT / "demo_web/services/hydrawise_riego.py").read_text(encoding="utf-8")
        self.assertIn("hydrawise_relay_id=int(relay_id)", riego)
