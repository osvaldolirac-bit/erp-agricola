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
        self.assertIn("Notas y condiciones", plano)
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
        self.assertIn("Notas y condiciones", html)
        self.assertIn("condiciones_def", html)
        self.assertIn('name="notas"', html)
        self.assertNotIn("Notas internas", html)
        detalle = (
            ROOT / "riomaipo_vps/rmweb/templates/cotizaciones/detalle.html"
        ).read_text(encoding="utf-8")
        self.assertIn("Notas y condiciones", detalle)
        self.assertIn("cot.notas", detalle)
        self.assertIn(">Proyecto<", detalle)
        self.assertIn("cot.proyecto", detalle)
        self.assertIn(">Asunto<", detalle)
        self.assertIn("cot.asunto", detalle)
        lista = (
            ROOT / "riomaipo_vps/rmweb/templates/cotizaciones/lista.html"
        ).read_text(encoding="utf-8")
        self.assertIn("Proyecto: {{ r.proyecto }}", lista)
        self.assertIn("Asunto: {{ r.asunto }}", lista)

    def test_el_pdf_muestra_proyecto_y_asunto(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb.core import cotizacion_pdf_bytes

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE cotizaciones (
                   folio TEXT, estado TEXT, fecha TEXT, razon_social TEXT,
                   titulo TEXT, version TEXT, proyecto TEXT, asunto TEXT,
                   gg_pct REAL, utilidad_pct REAL,
                   gg_monto REAL, utilidad_monto REAL, valor_neto REAL,
                   iva REAL, total REAL, notas TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO cotizaciones VALUES (
                   'COT-28_2026', 'borrador', '2026-11-19', 'SALVADOR GARCES',
                   'SALVADOR GARCES', '1', 'Fray Montalva', 'Fogón',
                   5, 15, 0, 0, 0, 0, 0, ''
               )"""
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        conn.execute(
            """CREATE TABLE items (
                   descripcion TEXT, obs TEXT, unidad TEXT,
                   cantidad REAL, precio_unitario REAL, total REAL
               )"""
        )
        conn.execute("INSERT INTO items VALUES ('Adoquin', '', 'm2', 10, 1000, 10000)")
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
        self.assertIn("Proyecto: Fray Montalva", plano)
        self.assertIn("Asunto: Fogón", plano)

    def test_el_archivo_pdf_se_llama_con_cliente_proyecto_y_asunto(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb.core import cotizacion_nombre_pdf

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE cotizaciones (
                   folio TEXT, razon_social TEXT, proyecto TEXT, asunto TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO cotizaciones VALUES (
                   'COT-28_2026', 'SALVADOR GARCÉS BERNALES', 'Fray Montalva', 'Fogón'
               )"""
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        nombre = cotizacion_nombre_pdf(cot)
        self.assertEqual(
            nombre,
            "COT-28_2026 - SALVADOR GARCÉS BERNALES - Fray Montalva - Fogón.pdf",
        )
        conn.execute(
            "UPDATE cotizaciones SET asunto='plano/corte: norte', proyecto='' WHERE folio='COT-28_2026'"
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        limpio = cotizacion_nombre_pdf(cot)
        self.assertNotIn("/", limpio)
        self.assertNotIn(":", limpio)
        self.assertTrue(limpio.endswith(".pdf"))
        app = (ROOT / "riomaipo_vps/rmweb/app.py").read_text(encoding="utf-8")
        self.assertIn("download_name=core.cotizacion_nombre_pdf(cot)", app)

    def test_el_iva_en_cero_se_queda_en_cero(self):
        import sys

        sys.path.insert(0, str(ROOT / "riomaipo_vps"))
        from rmweb.core import (
            _cotizacion_planilla_totales,
            cotizacion_iva_pct,
            cotizacion_pdf_bytes,
        )

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE cotizaciones (
                   folio TEXT, estado TEXT, fecha TEXT, razon_social TEXT, titulo TEXT,
                   gg_pct REAL, utilidad_pct REAL, gg_monto REAL, utilidad_monto REAL,
                   valor_neto REAL, iva REAL, total REAL, iva_pct REAL, notas TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO cotizaciones VALUES (
                   'COT-29_2026', 'borrador', '2026-11-19', 'SALVADOR', 'SALVADOR',
                   5, 15, 17250, 51750, 414000, 0, 414000, 0, ''
               )"""
        )
        cot = conn.execute("SELECT * FROM cotizaciones").fetchone()
        self.assertEqual(cotizacion_iva_pct(cot), 0.0)
        conn.execute(
            """CREATE TABLE items (
                   descripcion TEXT, unidad TEXT, cantidad REAL,
                   precio_unitario REAL, total REAL
               )"""
        )
        conn.execute("INSERT INTO items VALUES ('materiales y moldajes', 'un', 1, 145000, 145000)")
        conn.execute("INSERT INTO items VALUES ('MO', 'un', 1, 200000, 200000)")
        items = conn.execute("SELECT * FROM items").fetchall()
        plan = _cotizacion_planilla_totales(cot, items, iva_pct=0.0)
        self.assertEqual(plan["subtotal"], 345000)
        self.assertEqual(plan["gg"], 17250)
        self.assertEqual(plan["util"], 51750)
        self.assertEqual(plan["neto"], 414000)
        self.assertEqual(plan["iva"], 0)
        self.assertEqual(plan["iva_pct"], 0)
        self.assertEqual(plan["total"], 414000)
        pdf = cotizacion_pdf_bytes(cot, items, None, iva_pct=0.0)
        partes = []
        for raw in re.findall(br"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
            try:
                partes.append(zlib.decompress(raw).decode("latin-1", "replace"))
            except zlib.error:
                continue
        plano = "\n".join(partes)
        self.assertIn("IVA 0%", plano)
        self.assertNotIn("IVA 19%", plano)
        app = (ROOT / "riomaipo_vps/rmweb/app.py").read_text(encoding="utf-8")
        self.assertIn("def _form_iva_pct", app)
        self.assertIn("En blanco significa 0", app)
        form = (
            ROOT / "riomaipo_vps/rmweb/templates/cotizaciones/form.html"
        ).read_text(encoding="utf-8")
        self.assertIn("iva_cot if iva_cot is not none else iva_def", form)


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

    def test_el_borrador_nuevo_trae_notas_y_condiciones(self):
        core = self._core()
        texto = core.CONDICIONES_COTIZACION_DEFECTO
        self.assertIn("Validez:", texto)
        self.assertIn("Alcance:", texto)
        self.assertIn("Garantía:", texto)
        self.assertIn("Forma de pago:", texto)
        app = (ROOT / "riomaipo_vps/rmweb/app.py").read_text(encoding="utf-8")
        self.assertIn("condiciones_def=core.CONDICIONES_COTIZACION_DEFECTO", app)


class MenuModulosTests(unittest.TestCase):
    def test_el_menu_recibe_modulo_visible(self):
        app_py = (ROOT / "riomaipo_vps/rmweb/app.py").read_text(encoding="utf-8")
        self.assertIn("modulo_visible", app_py)
        self.assertIn('ctx["modulo_visible"]', app_py)
        self.assertIn("register_taller_routes", app_py)
        self.assertIn("register_rrhh_routes", app_py)


class SidebarMovilTests(unittest.TestCase):
    def test_el_menu_movil_parte_oculto_con_las_tres_rayas(self):
        base = (ROOT / "riomaipo_vps/rmweb/templates/base.html").read_text(encoding="utf-8")
        css = (ROOT / "riomaipo_vps/rmweb/static/css/app.css").read_text(encoding="utf-8")
        self.assertIn('id="appMenu"', base)
        self.assertIn('aria-label="Menú"', base)
        self.assertIn("mobile-topbar", base)
        self.assertIn("navbar-toggler-icon", base)
        self.assertNotIn(".sidebar { width: 100%; height: auto; position: relative; }", css)
        self.assertIn("translateX(-100%)", css)
        self.assertIn("@media (max-width: 991.98px)", css)
        self.assertIn("@media (min-width: 992px)", css)

    def test_el_sidebar_no_tiene_cursor(self):
        base = (ROOT / "riomaipo_vps/rmweb/templates/base.html").read_text(encoding="utf-8")
        self.assertNotIn("Con Cursor", base)
        self.assertNotIn("cotizaciones_cursor", base)
        self.assertNotIn("cursor.com/link/prompt", base)
        app = (ROOT / "riomaipo_vps/rmweb/app.py").read_text(encoding="utf-8")
        self.assertNotIn("/cotizaciones/cursor", app)


if __name__ == "__main__":
    unittest.main()
