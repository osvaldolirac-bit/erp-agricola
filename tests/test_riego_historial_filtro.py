"""Historial de riego: filtro por fecha y huerto, PDF solo al descargar."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_web.services.registro_riego import listar_historial

ROOT = Path(__file__).resolve().parents[1]


class _Demo:
    def f_decimal(self, valor):
        return str(valor)

    f_cantidad = f_decimal


class RiegoHistorialFiltroTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE riego (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT, fecha TEXT, huerto TEXT,
                   horas REAL, m3 REAL, fert_dosis_ha REAL, fert_total REAL,
                   regador TEXT, origen TEXT, bitacora_codigo TEXT,
                   creado_por TEXT, creado_en TEXT,
                   modo_riego TEXT, surcos REAL, fert_estado TEXT
               )"""
        )
        self.conn.execute(
            """CREATE TABLE riego_fertilizantes (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT, producto_id INTEGER, producto TEXT,
                   cantidad REAL, dosis_ha REAL, unidad TEXT
               )"""
        )
        self.conn.executemany(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, regador, origen, creado_en, modo_riego)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                ("R1", "2026-10-01", "NOGALES APARICION", 1, 10, "Ana", "manual", "2026-10-01", "horas"),
                ("R2", "2026-10-20", "CIRUELOS", 2, 20, "Luis", "manual", "2026-10-20", "horas"),
                ("R3", "2026-09-01", "NOGALES APARICION", 3, 30, "Ana", "manual", "2026-09-01", "horas"),
            ],
        )

    def tearDown(self):
        self.conn.close()

    def _listar(self, **kwargs):
        with (
            patch("demo_web.services.registro_riego.migrar_tabla"),
            patch("demo_web.services.registro_riego._fertilizantes_por_codigos", return_value={}),
            patch("demo_web.services.registro_riego._npk_evento_fmt", return_value={}),
        ):
            return listar_historial(self.conn, limite=None, demo=_Demo(), **kwargs)

    def test_filtra_por_fecha_y_huerto(self):
        rows = self._listar(desde="2026-10-01", hasta="2026-10-31", huerto="nogales aparicion")
        self.assertEqual([r["codigo"] for r in rows], ["R1"])

    def test_sin_huerto_respeta_el_periodo(self):
        rows = self._listar(desde="2026-10-01", hasta="2026-10-31")
        self.assertEqual([r["codigo"] for r in rows], ["R2", "R1"])

    def test_la_pantalla_no_arma_el_pdf_y_el_boton_si_esta(self):
        src = (ROOT / "demo_web/services/native/riego.py").read_text()
        gather = src.split("def gather_riego", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("generar_pdf_blob", gather)
        self.assertNotIn("_blob_historial", gather)
        self.assertIn('request.args.get("pdf") == "1"', src)
        self.assertIn("pdf=\"\"", src)
        html = (ROOT / "demo_web/templates/modules/riego.html").read_text()
        historial = html.split("sec_activa == 'historial'", 1)[1]
        self.assertIn('name="desde"', historial)
        self.assertIn('name="hasta"', historial)
        self.assertIn('name="huerto"', historial)
        self.assertIn("PDF HISTORIAL", historial)
        self.assertIn("pdf_historial_url", historial)


if __name__ == "__main__":
    unittest.main()
