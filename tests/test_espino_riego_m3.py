"""El Espino calcula m³ = horas × 18 m³/h·ha × superficie de la variedad."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.registro_riego import (
    calcular_m3_riego,
    completar_m3_pendiente,
)


class EspinoRiegoM3Tests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE prorrateo_cc (
                   centro_costo TEXT PRIMARY KEY,
                   superficie_ha REAL
               )"""
        )
        self.conn.executemany(
            "INSERT INTO prorrateo_cc (centro_costo, superficie_ha) VALUES (?,?)",
            [
                ("SWEET ARYANA", 1.0),
                ("ROYAL DOWN", 1.5),
                ("SANTINA", 4.5),
            ],
        )
        self.conn.execute(
            """CREATE TABLE riego (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT,
                   huerto TEXT,
                   horas REAL,
                   m3 REAL,
                   modo_riego TEXT
               )"""
        )
        self.conn.execute(
            """CREATE TABLE riego_fertilizantes (
                   codigo TEXT,
                   producto TEXT,
                   cantidad REAL
               )"""
        )

    def tearDown(self):
        self.conn.close()

    def test_cada_variedad_usa_18_por_su_superficie(self):
        aryana, err = calcular_m3_riego(self.conn, "SWEET ARYANA", 6.5)
        self.assertEqual(err, "")
        self.assertEqual(aryana, 117.0)
        royal, _ = calcular_m3_riego(self.conn, "royal down", 5)
        self.assertEqual(royal, 135.0)
        santina, _ = calcular_m3_riego(self.conn, "SANTINA", 6.6)
        self.assertEqual(santina, 534.6)

    def test_completa_los_m3_en_cero_y_no_pisa_los_que_ya_estan(self):
        self.conn.executemany(
            "INSERT INTO riego (codigo, huerto, horas, m3, modo_riego) VALUES (?,?,?,?, 'horas')",
            [
                ("RIE-01", "SWEET ARYANA", 6.5, 117.0, ),
                ("RIE-11", "SWEET ARYANA", 2, 0, ),
                ("RIE-10", "ROYAL DOWN", 5, 0, ),
            ],
        )
        self.conn.execute(
            "INSERT INTO riego_fertilizantes (codigo, producto, cantidad) VALUES ('RIE-11', 'UREA', 75)"
        )
        n = completar_m3_pendiente(self.conn)
        self.assertEqual(n, 2)
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-01'").fetchone()[0],
            117.0,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-11'").fetchone()[0],
            36.0,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-10'").fetchone()[0],
            135.0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT cantidad FROM riego_fertilizantes WHERE codigo='RIE-11'"
            ).fetchone()[0],
            75,
        )
        self.assertEqual(completar_m3_pendiente(self.conn), 0)


if __name__ == "__main__":
    unittest.main()
