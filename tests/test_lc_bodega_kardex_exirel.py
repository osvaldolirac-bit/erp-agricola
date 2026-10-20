"""Kardex LC: una app de Libro de Campo sin salida no mueve el saldo.

Caso EXIREL: stock 0,1 L, salida real 3,4 L (2025-10-30) e ingreso 3,0 L
(2026-10-05). La app de 10 L del 2025-12-01 no tiene movimiento de bodega
y no debe inflar la apertura.
"""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime

from demo_web.services.bodega_kardex import gather_kardex_producto


class _Demo:
    DEFAULT_UNIDAD_INSUMO = "lt"
    CENTROS_COSTO = ["CEREZOS CORTE 1", "CIRUELOS"]
    TEMPORADAS_COSTOS = [
        ("2026-2027", datetime(2026, 5, 1).date(), datetime(2027, 4, 30).date()),
    ]

    def f_cantidad(self, x):
        return f"{float(x):.1f}"

    def hora_chile(self):
        return datetime(2026, 10, 20, 12, 0, 0)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE inventario (
            id INTEGER PRIMARY KEY, producto TEXT, familia TEXT,
            unidad_medida TEXT, stock REAL, ingrediente_activo TEXT)"""
    )
    conn.execute(
        """CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY, producto_id INTEGER, tipo TEXT,
            cantidad REAL, fecha TEXT, centro_costo TEXT)"""
    )
    conn.execute(
        """CREATE TABLE libro_campo (
            id INTEGER PRIMARY KEY, n_aplicacion INTEGER, fecha TEXT,
            sector TEXT, producto TEXT, gasto_total REAL)"""
    )
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY, nro_documento TEXT, fecha_compra TEXT,
            concepto TEXT)"""
    )
    conn.execute(
        "INSERT INTO inventario VALUES (24, 'EXIREL', 'INSECTICIDA', 'lt', 0.1, 'Ciantraniliprol')"
    )
    conn.execute(
        """INSERT INTO movimientos VALUES
           (106, 24, 'Salida', 3.4, '2025-10-30', 'CEREZOS CORTE 1'),
           (139, 24, 'Ingreso', 3.0, '2026-10-05', 'BODEGA')"""
    )
    conn.execute(
        """INSERT INTO libro_campo VALUES
           (61, 10045, '2025-10-30', 'CEREZOS CORTE 1', 'Exirel', 3.4),
           (108, 10086, '2025-12-01', 'CIRUELOS', 'Exirel', 10.0)"""
    )
    conn.execute(
        """INSERT INTO facturas VALUES
           (636, '30707', '2026-10-05', '[3.0 lt x EXIREL]')"""
    )
    return conn


class TestKardexExirel(unittest.TestCase):
    def test_app_sin_salida_no_infla_apertura_ni_saldo(self):
        data = gather_kardex_producto(_Demo(), _conn(), 24, include_pdf=False)
        rows = data["kardex_rows"]
        self.assertEqual([r["cant_raw"] for r in rows], [0.5, 3.4, 3.0])
        self.assertEqual([r["tipo"] for r in rows], ["Ingreso", "Salida", "Ingreso"])
        self.assertTrue(rows[0]["es_apertura"])
        self.assertEqual(rows[1]["fecha"], "2025-10-30")
        self.assertTrue(rows[1]["fuera_temporada"])
        self.assertIn("10045", rows[1]["origen"])
        self.assertFalse(rows[2]["fuera_temporada"])
        self.assertAlmostEqual(rows[-1]["saldo_raw"], 0.1)
        self.assertAlmostEqual(rows[1]["saldo_raw"], -2.9)
        self.assertEqual(data["kardex_producto"]["stock"], "0.1")
        self.assertEqual(data["kardex_producto"]["ing_total"], "3.5")
        self.assertEqual(data["kardex_producto"]["sal_total"], "3.4")
        pend = data["kardex_lc_pendientes"]
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["n_app"], 10086)
        self.assertEqual(pend[0]["fecha"], "2025-12-01")
        self.assertEqual(pend[0]["gasto"], "10.0")
        self.assertNotIn(10.0, [r["cant_raw"] for r in rows])


if __name__ == "__main__":
    unittest.main()
