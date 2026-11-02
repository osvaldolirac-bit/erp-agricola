"""La cotización de Río Maipo imprime las condiciones en el PDF."""
from __future__ import annotations

import re
import sqlite3
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CotizacionCondicionesPdfTests(unittest.TestCase):
    def test_el_pdf_lleva_el_texto_de_condiciones(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb.core import cotizacion_pdf_bytes

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE cotizaciones (
                   folio TEXT, estado TEXT, fecha TEXT, razon_social TEXT,
                   titulo TEXT, gg_pct REAL, utilidad_pct REAL,
                   gg_monto REAL, utilidad_monto REAL, valor_neto REAL,
                   iva REAL, total REAL, notas TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO cotizaciones VALUES (
                   'COT-0099', 'borrador', '2026-11-02', 'CLIENTE PRUEBA',
                   'OBRA FILTRO', 5, 15, 0, 0, 0, 0, 0,
                   'Validez de la propuesta: 7 dias. Forma de pago: 50 por ciento al aceptar.'
               )"""
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        conn.execute(
            """CREATE TABLE items (
                   descripcion TEXT, obs TEXT, unidad TEXT,
                   cantidad REAL, precio_unitario REAL, total REAL
               )"""
        )
        conn.execute(
            "INSERT INTO items VALUES ('Filtro', '', 'un', 1, 100000, 100000)"
        )
        items = conn.execute("SELECT * FROM items").fetchall()
        pdf = cotizacion_pdf_bytes(cot, items, None, iva_pct=0.19)
        self.assertGreater(len(pdf), 500)
        self.assertIn(b"/Count 2", pdf)
        partes = []
        for raw in re.findall(br"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
            try:
                partes.append(zlib.decompress(raw).decode("latin-1", "replace"))
            except zlib.error:
                continue
        plano = "\n".join(partes)
        self.assertIn("Condiciones de la cotizaci", plano)
        self.assertIn("Forma de pago", plano)
        self.assertIn("COT-0099", plano)

    def test_el_formulario_nombra_las_condiciones(self):
        html = (
            ROOT / "riomaipo_vps/rmweb/templates/cotizaciones/form.html"
        ).read_text(encoding="utf-8")
        self.assertIn("Condiciones de la cotización", html)
        self.assertIn('name="notas"', html)
        self.assertNotIn("Notas internas", html)


if __name__ == "__main__":
    unittest.main()
