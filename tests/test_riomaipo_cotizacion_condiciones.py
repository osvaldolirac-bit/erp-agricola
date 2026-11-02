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
        self.assertIn(b"/Count 1", pdf)
        partes = []
        for raw in re.findall(br"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
            try:
                partes.append(zlib.decompress(raw).decode("latin-1", "replace"))
            except zlib.error:
                continue
        plano = "\n".join(partes)
        self.assertIn("Condiciones", plano)
        self.assertIn("Forma de pago", plano)
        self.assertIn("COT-0099", plano)

    def test_un_texto_largo_sigue_en_la_hoja_1(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb.core import cotizacion_pdf_bytes

        largo = (
            "Validez de la propuesta: La presente cotizacion tiene una validez de 7 dias corridos "
            "a contar de su fecha de emision. Pasado este plazo, los valores quedan sujetos a confirmacion. "
            "Alcance del trabajo: el servicio contempla exclusivamente el suministro de materiales, "
            "equipos y mano de obra. Cualquier modificacion o vicios ocultos se cotiza por separado. "
            "Garantia y entrega: garantia de 6 meses por mano de obra. "
            "Forma de pago: 50 por ciento al aceptar y 50 contra entrega conforme y prueba del equipo."
        )
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
                   'COT-0027', 'borrador', '2026-11-02', 'ROBERTO BRICENO',
                   'FILTRO', 5, 15, 0, 0, 0, 0, 0, ?
               )""",
            (largo,),
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        conn.execute(
            """CREATE TABLE items (
                   descripcion TEXT, obs TEXT, unidad TEXT,
                   cantidad REAL, precio_unitario REAL, total REAL
               )"""
        )
        conn.execute("INSERT INTO items VALUES ('Filtro', '', 'un', 1, 100000, 100000)")
        items = conn.execute("SELECT * FROM items").fetchall()
        pdf = cotizacion_pdf_bytes(cot, items, None, iva_pct=0.19)
        self.assertIn(b"/Count 1", pdf)
        partes = []
        for raw in re.findall(br"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
            try:
                partes.append(zlib.decompress(raw).decode("latin-1", "replace"))
            except zlib.error:
                continue
        plano = "\n".join(partes)
        self.assertIn("Validez de la propuesta", plano)
        self.assertIn("Forma de pago", plano)
        self.assertIn("contra entrega", plano)

    def test_el_formulario_nombra_las_condiciones(self):
        html = (
            ROOT / "riomaipo_vps/rmweb/templates/cotizaciones/form.html"
        ).read_text(encoding="utf-8")
        self.assertIn("Condiciones de la cotización", html)
        self.assertIn('name="notas"', html)
        self.assertNotIn("Notas internas", html)


class FolioCotizacionAnioTests(unittest.TestCase):
    def _core(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb import core

        return core

    def test_renumera_por_fecha_y_actualiza_las_citas(self):
        core = self._core()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE cotizaciones (
                   id INTEGER PRIMARY KEY, folio TEXT UNIQUE, fecha TEXT
               )"""
        )
        conn.execute(
            """CREATE TABLE cuentas (
                   id INTEGER PRIMARY KEY, documento TEXT UNIQUE, concepto TEXT
               )"""
        )
        conn.executemany(
            "INSERT INTO cotizaciones (id, folio, fecha) VALUES (?,?,?)",
            [
                (20, "COT-1000", "2026-04-15"),
                (16, "COT-1004", "2026-04-15"),
                (30, "COT-0027", "2026-11-02"),
                (2, "COT-1018", "2025-12-01"),
            ],
        )
        conn.execute(
            "INSERT INTO cuentas (id, documento, concepto) VALUES (1, 'COT-1000', 'Desde cotización COT-1000 · obra')"
        )
        n = core.renumerar_folios_cotizacion(conn)
        self.assertEqual(n, 4)
        folios = {
            r["id"]: r["folio"]
            for r in conn.execute("SELECT id, folio FROM cotizaciones")
        }
        self.assertEqual(folios[20], "COT-1000_2026")
        self.assertEqual(folios[16], "COT-1004_2026")
        self.assertEqual(folios[30], "COT-27_2026")
        self.assertEqual(folios[2], "COT-1018_2025")
        cuenta = conn.execute("SELECT documento, concepto FROM cuentas WHERE id=1").fetchone()
        self.assertEqual(cuenta["documento"], "COT-1000_2026")
        self.assertIn("COT-1000_2026", cuenta["concepto"])
        self.assertEqual(core.renumerar_folios_cotizacion(conn), 0)
        self.assertEqual(core.siguiente_folio_cotizacion(conn, "2026-11-02"), "COT-28_2026")


if __name__ == "__main__":
    unittest.main()
