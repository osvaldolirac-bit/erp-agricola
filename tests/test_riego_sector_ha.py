"""NOGALES APARICION: cada sector riega 1/4 de las 7 ha del prorrateo."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_web.services.registro_riego import (
    _npk_evento_fmt,
    calcular_m3_riego,
    corregir_m3_por_sector,
    resumen_npk_por_huerto,
)

ROOT = Path(__file__).resolve().parents[1]


class _Demo:
    def f_decimal(self, valor):
        return str(valor)

    f_cantidad = f_decimal


class RiegoSectorHaTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE prorrateo_cc (
                   centro_costo TEXT PRIMARY KEY,
                   superficie_ha REAL
               )"""
        )
        self.conn.execute(
            """CREATE TABLE hydrawise_zona (
                   relay_id INTEGER PRIMARY KEY,
                   huerto_cc TEXT,
                   activo INTEGER
               )"""
        )
        self.conn.execute(
            """CREATE TABLE riego (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT,
                   fecha TEXT,
                   huerto TEXT,
                   horas REAL,
                   m3 REAL,
                   modo_riego TEXT
               )"""
        )
        self.conn.execute(
            """CREATE TABLE riego_bitacora (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT,
                   huerto TEXT,
                   horas REAL,
                   m3 REAL,
                   estado TEXT,
                   modo_riego TEXT
               )"""
        )
        self.conn.execute(
            """CREATE TABLE riego_fertilizantes (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT,
                   producto_id INTEGER,
                   producto TEXT,
                   cantidad REAL,
                   unidad TEXT,
                   dosis_ha REAL,
                   n_pct REAL,
                   p_pct REAL,
                   k_pct REAL,
                   npk_reconocido INTEGER
               )"""
        )
        self.conn.execute(
            "INSERT INTO prorrateo_cc (centro_costo, superficie_ha) VALUES ('NOGALES APARICION', 7)"
        )
        self.conn.execute(
            "INSERT INTO prorrateo_cc (centro_costo, superficie_ha) VALUES ('CEREZOS CORTE 1', 1.7)"
        )
        self.conn.executemany(
            "INSERT INTO hydrawise_zona (relay_id, huerto_cc, activo) VALUES (?,?,1)",
            [
                (1, "NOGALES APARICION"),
                (2, "NOGALES APARICION"),
                (3, "NOGALES APARICION"),
                (4, "NOGALES APARICION"),
                (5, "CEREZOS CORTE 1"),
            ],
        )

    def tearDown(self):
        self.conn.close()

    def test_m3_de_nogales_usa_un_cuarto_de_las_7_ha(self):
        m3, err = calcular_m3_riego(self.conn, "NOGALES APARICION", 2)
        self.assertEqual(err, "")
        self.assertEqual(m3, 119.0)
        m3_26, _ = calcular_m3_riego(self.conn, "nogales aparicion", 1.9975)
        self.assertEqual(m3_26, 118.85)

    def test_un_solo_sector_sigue_con_la_ha_del_huerto(self):
        m3, err = calcular_m3_riego(self.conn, "CEREZOS CORTE 1", 2)
        self.assertEqual(err, "")
        self.assertEqual(m3, round(2 * 18 * 1.7, 2))

    def test_sin_sectores_usa_la_ha_completa(self):
        self.conn.execute("DELETE FROM hydrawise_zona WHERE huerto_cc='NOGALES APARICION'")
        m3, _ = calcular_m3_riego(self.conn, "NOGALES APARICION", 2)
        self.assertEqual(m3, 476.0)

    def test_corrige_m3_guardado_y_no_toca_fertilizante_ni_prorrateo(self):
        self.conn.execute(
            """INSERT INTO riego (codigo, fecha, huerto, horas, m3, modo_riego)
               VALUES ('RIE-05', '2026-09-21', 'NOGALES APARICION', 2, 476, 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego (codigo, fecha, huerto, horas, m3, modo_riego)
               VALUES ('RIE-26', '2026-10-29', 'NOGALES APARICION', 1.9975, 475.41, 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego (codigo, fecha, huerto, horas, m3, modo_riego)
               VALUES ('RIE-99', '2026-10-29', 'NOGALES APARICION', 2, 999, 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego (codigo, fecha, huerto, horas, m3, modo_riego)
               VALUES ('RIE-C', '2026-10-01', 'CEREZOS CORTE 1', 2, 61.2, 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego_bitacora (codigo, huerto, horas, m3, estado, modo_riego)
               VALUES ('RIE-05', 'NOGALES APARICION', 2, 476, 'autorizado', 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego_bitacora (codigo, huerto, horas, m3, estado, modo_riego)
               VALUES ('RIE-19', 'NOGALES APARICION', 0.10055555555555555, 23.93, 'rechazado', 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego_fertilizantes
               (codigo, producto_id, producto, cantidad, unidad, dosis_ha, n_pct, p_pct, k_pct, npk_reconocido)
               VALUES ('RIE-26', 1, 'UREA', 18, 'kg', NULL, 46, 0, 0, 1)"""
        )
        n = corregir_m3_por_sector(self.conn)
        self.assertEqual(n, 4)
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-05'").fetchone()[0],
            119.0,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-26'").fetchone()[0],
            118.85,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego_bitacora WHERE codigo='RIE-05'").fetchone()[0],
            119.0,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego_bitacora WHERE codigo='RIE-19'").fetchone()[0],
            5.98,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-99'").fetchone()[0],
            999,
        )
        self.assertEqual(
            self.conn.execute("SELECT m3 FROM riego WHERE codigo='RIE-C'").fetchone()[0],
            61.2,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT cantidad, dosis_ha FROM riego_fertilizantes WHERE codigo='RIE-26'"
            ).fetchone(),
            (18, None),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT superficie_ha FROM prorrateo_cc WHERE centro_costo='NOGALES APARICION'"
            ).fetchone()[0],
            7,
        )
        self.assertEqual(corregir_m3_por_sector(self.conn), 0)

    def test_la_fila_usa_1_75_y_el_balance_del_huerto_sigue_en_7(self):
        self.conn.execute(
            """INSERT INTO riego (codigo, fecha, huerto, horas, m3, modo_riego)
               VALUES ('RIE-22', '2026-10-28', 'NOGALES APARICION', 1.5, 89.25, 'horas')"""
        )
        self.conn.execute(
            """INSERT INTO riego_fertilizantes
               (codigo, producto_id, producto, cantidad, unidad, dosis_ha,
                n_pct, p_pct, k_pct, npk_reconocido)
               VALUES ('RIE-22', 1, 'UREA', 18, 'kg', NULL, 46, 0, 0, 1)"""
        )
        fmt = _npk_evento_fmt(
            self.conn,
            "NOGALES APARICION",
            [("UREA", 1, 18, "kg", 46, 0, 0, 1)],
            lambda v: f"{float(v):.4f}",
        )
        self.assertEqual(fmt["ha"], 1.75)
        self.assertEqual(fmt["n_ha_fmt"], f"{18 * 0.46 / 1.75:.4f}")
        with (
            patch("demo_web.services.registro_riego.migrar_tabla"),
            patch("demo_web.services.registro_riego.get_demo_module", return_value=_Demo()),
        ):
            resumen = resumen_npk_por_huerto(self.conn, huerto="NOGALES APARICION")
        fila = resumen["filas"][0]
        self.assertEqual(fila["ha"], 7.0)
        self.assertAlmostEqual(fila["n_ha"], 18 * 0.46 / 7.0)

    def test_el_pdf_del_historial_lleva_la_superficie(self):
        src = (ROOT / "demo_web/services/native/riego.py").read_text(encoding="utf-8")
        bloque = src.split("def _blob_historial", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('"ha"', bloque)
        html = (ROOT / "demo_web/templates/modules/riego.html").read_text(encoding="utf-8")
        self.assertIn("ha/sector", html)
        params = (ROOT / "demo_web/templates/partials/riego_parametros.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("ha/sector", params)
        self.assertIn("ha del huerto", params)


if __name__ == "__main__":
    unittest.main()
