"""El Espino: el registro manual de riego guarda una nota."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_web.services.registro_riego import listar_historial, nota_riego

ROOT = Path(__file__).resolve().parents[1]


class _Demo:
    def f_decimal(self, valor):
        return str(valor)

    f_cantidad = f_decimal


class EspinoRiegoNotaTests(unittest.TestCase):
    def test_nota_recorta_y_limpia(self):
        self.assertEqual(nota_riego("  sector norte  "), "sector norte")
        self.assertEqual(nota_riego(None), "")
        self.assertEqual(len(nota_riego("x" * 800)), 500)

    def test_el_historial_muestra_la_nota(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE riego (
                   id INTEGER PRIMARY KEY,
                   codigo TEXT, fecha TEXT, huerto TEXT,
                   horas REAL, m3 REAL, fert_dosis_ha REAL, fert_total REAL,
                   regador TEXT, origen TEXT, bitacora_codigo TEXT,
                   creado_por TEXT, creado_en TEXT,
                   modo_riego TEXT, surcos REAL, fert_estado TEXT,
                   notas TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            """CREATE TABLE riego_fertilizantes (
                   id INTEGER PRIMARY KEY, codigo TEXT, producto_id INTEGER,
                   producto TEXT, cantidad REAL, dosis_ha REAL, unidad TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO riego
               (codigo, fecha, huerto, horas, m3, regador, origen, creado_en, notas)
               VALUES ('R9', '2026-11-01', 'SANTINA', 2, 36, 'Ana', 'manual', '2026-11-01', 'filtro tapado')"""
        )
        with (
            patch("demo_web.services.registro_riego.migrar_tabla"),
            patch("demo_web.services.registro_riego._fertilizantes_por_codigos", return_value={}),
            patch("demo_web.services.registro_riego._npk_evento_fmt", return_value={}),
        ):
            rows = listar_historial(conn, limite=None, demo=_Demo())
        self.assertEqual(rows[0]["nota"], "filtro tapado")
        conn.close()

    def test_el_formulario_de_espino_pide_la_nota(self):
        html = (ROOT / "demo_web/templates/modules/riego.html").read_text(encoding="utf-8")
        manual = html.split("formManualRiego", 1)[1].split("</form>", 1)[0]
        self.assertIn("{% if riego_espino %}", manual)
        self.assertIn('name="nota"', manual)
        src = (ROOT / "demo_web/services/native/riego.py").read_text(encoding="utf-8")
        post = src.split("def _post_manual", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("is_espino_tenant()", post)
        self.assertIn("nota=nota", post)
        registro = (ROOT / "demo_web/services/registro_riego.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN notas", registro)


if __name__ == "__main__":
    unittest.main()
