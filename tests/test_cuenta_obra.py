"""La utilidad de la cuenta obra parte en el neto y baja con cada gasto imputado."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "riomaipo_vps"))

from rmweb import core  # noqa: E402


class CompraMontoUnicoTest(unittest.TestCase):
    def test_con_factura_el_monto_es_el_total_y_se_imputa_el_neto(self) -> None:
        m = core.montos_compra_unica("factura", 189980)
        self.assertEqual(m["total"], 189980)
        self.assertEqual(m["neto"], 159647)
        self.assertEqual(m["iva"], 30333)
        self.assertEqual(m["cc_base"], "neto")

    def test_con_factura_la_casilla_de_bruto_imputa_el_total(self) -> None:
        m = core.montos_compra_unica("factura", 189980, imputar_bruto=True)
        self.assertEqual(m["total"], 189980)
        self.assertEqual(m["neto"], 159647)
        self.assertEqual(m["cc_base"], "bruto")

    def test_sin_factura_imputa_el_monto_completo(self) -> None:
        for tipo in ("boleta", "guia", "otro"):
            m = core.montos_compra_unica(tipo, 80000)
            self.assertEqual(m["neto"], 80000, tipo)
            self.assertEqual(m["iva"], 0, tipo)
            self.assertEqual(m["total"], 80000, tipo)
            self.assertEqual(m["cc_base"], "bruto", tipo)


class ResultadoCuentaObraTest(unittest.TestCase):
    def test_sin_gastos_la_utilidad_es_el_neto(self) -> None:
        r = core.resultado_cuenta_obra(valor_neto=2030382, subtotal=1691985, compras=0, mo_pagada=0)
        self.assertEqual(r["utilidad"], 2030382)
        self.assertEqual(r["gasto"], 0)
        self.assertEqual(r["pct"], 0)
        self.assertEqual(r["alerta"], "")
        self.assertEqual(r["color"], "#1b7f4e")

    def test_cada_gasto_achica_la_utilidad(self) -> None:
        r = core.resultado_cuenta_obra(
            valor_neto=2030382, subtotal=1691985, compras=100000, mo_pagada=200000
        )
        self.assertEqual(r["gasto"], 300000)
        self.assertEqual(r["utilidad"], 1730382)

    def test_alerta_si_se_come_gg_y_utilidad(self) -> None:
        r = core.resultado_cuenta_obra(
            valor_neto=2030382, subtotal=1691985, compras=1700000, mo_pagada=0
        )
        self.assertEqual(r["nivel"], "warning")
        self.assertIn("subtotal neto", r["alerta"])
        self.assertNotEqual(r["color"], "#1b7f4e")

    def test_alerta_si_supera_el_neto(self) -> None:
        r = core.resultado_cuenta_obra(
            valor_neto=1000, subtotal=800, compras=900, mo_pagada=200
        )
        self.assertEqual(r["utilidad"], -100)
        self.assertEqual(r["pct"], 110.0)
        self.assertEqual(r["ancho"], 100.0)
        self.assertEqual(r["nivel"], "danger")
        self.assertEqual(r["color"], "#7b1113")

    def test_imputar_una_compra_baja_la_utilidad(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """
            CREATE TABLE cotizaciones (
                id INTEGER PRIMARY KEY, estado TEXT, folio TEXT, proyecto TEXT,
                asunto TEXT, titulo TEXT, cliente_id INTEGER, centro_costo_id INTEGER,
                subtotal REAL, valor_neto REAL, total REAL, gg_monto REAL, contratista_id INTEGER
            )
            """
        )
        db.execute(
            """
            CREATE TABLE facturas_compra (
                id INTEGER PRIMARY KEY, documento TEXT, neto REAL, concepto TEXT,
                fecha_emision TEXT, proveedor_id INTEGER
            )
            """
        )
        db.execute("CREATE TABLE proveedores (id INTEGER PRIMARY KEY, razon_social TEXT)")
        db.execute(
            "INSERT INTO cotizaciones (id, estado, folio, proyecto, asunto, subtotal, valor_neto, total) "
            "VALUES (1, 'aprobada', 'COT-30_2026', 'Fray Montalva', 'Elevaciones', 1691985, 2030382, 2030382)"
        )
        db.execute(
            "INSERT INTO proveedores (id, razon_social) VALUES (1, 'Ferretería')"
        )
        db.execute(
            "INSERT INTO facturas_compra (id, documento, neto, concepto, fecha_emision, proveedor_id) "
            "VALUES (7, '58707', 55882, 'batería', '2026-11-24', 1)"
        )
        ok, err = core.imputar_gasto_cotizacion(db, 1, 7, None)
        self.assertTrue(ok, err)
        gastos = core.gastos_imputados_cotizacion(db, 1)
        self.assertEqual(len(gastos), 1)
        self.assertEqual(gastos[0]["monto"], 55882)
        r = core.resultado_cuenta_obra(
            valor_neto=2030382, subtotal=1691985, compras=55882, mo_pagada=0
        )
        self.assertEqual(r["utilidad"], 2030382 - 55882)
        ok, err = core.imputar_gasto_cotizacion(db, 1, 7, 999999)
        self.assertFalse(ok)

    def test_una_compra_en_otro_centro_se_puede_mover_a_la_cotizacion(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """
            CREATE TABLE cotizaciones (
                id INTEGER PRIMARY KEY, estado TEXT, folio TEXT, proyecto TEXT,
                asunto TEXT, titulo TEXT, cliente_id INTEGER, centro_costo_id INTEGER,
                subtotal REAL, valor_neto REAL, total REAL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE facturas_compra (
                id INTEGER PRIMARY KEY, documento TEXT, neto REAL, concepto TEXT,
                fecha_emision TEXT, proveedor_id INTEGER
            )
            """
        )
        db.execute("CREATE TABLE proveedores (id INTEGER PRIMARY KEY, razon_social TEXT)")
        db.execute(
            "INSERT INTO cotizaciones (id, estado, folio, proyecto, subtotal, valor_neto, total) "
            "VALUES (1, 'aprobada', 'COT-30_2026', 'Fray Montalva', 1691985, 2030382, 2030382)"
        )
        db.execute("INSERT INTO proveedores (id, razon_social) VALUES (4, 'HUAFA')")
        db.execute(
            "INSERT INTO facturas_compra (id, documento, neto, concepto, fecha_emision, proveedor_id) "
            "VALUES (4, '20054935', 35000, 'Materiales cot-30', '2026-11-23', 4)"
        )
        core.ensure_obra_schema(db)
        db.execute(
            "INSERT INTO centros_costo (id, nombre, activo, tipo) VALUES (2, 'Operaciones', 1, 'general')"
        )
        db.execute(
            "INSERT INTO factura_compra_cc (factura_id, centro_costo_id, monto) VALUES (4, 2, 35000)"
        )
        opciones = core.facturas_para_imputar(db, 1)
        self.assertEqual([f["id"] for f in opciones], [4])
        self.assertIn("Operaciones", opciones[0]["otros_nombres"])
        ok, err = core.imputar_gasto_cotizacion(db, 1, 4, None)
        self.assertTrue(ok, err)
        centros = db.execute(
            "SELECT centro_costo_id, monto FROM factura_compra_cc WHERE factura_id=4"
        ).fetchall()
        self.assertEqual(len(centros), 1)
        self.assertEqual(centros[0]["monto"], 35000)
        self.assertNotEqual(centros[0]["centro_costo_id"], 2)
