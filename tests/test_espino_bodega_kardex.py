"""Bodega Espino: kardex CC EL ESPINO + legado Cerezos."""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from demo_web.services.native import espino_bodega


class DemoStub:
    DEFAULT_UNIDAD_INSUMO = "L"

    def f_cantidad(self, x):
        return str(x)


class TestEspinoBodegaKardex(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE inventario (
                id INTEGER PRIMARY KEY, producto TEXT, precio_medio REAL,
                unidad_medida TEXT, stock REAL)"""
        )
        self.conn.execute(
            """CREATE TABLE movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER, tipo TEXT, cantidad REAL, fecha TEXT,
                centro_costo TEXT, valor_imputado REAL, unidad_medida TEXT)"""
        )
        self.conn.execute(
            "INSERT INTO inventario (id, producto, precio_medio, unidad_medida, stock) VALUES (1,'PIRIPROXIFEN',10,'L',0)"
        )
        self.conn.execute(
            """INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (1,'Ingreso',100,'2026-01-01','EL ESPINO',1000,'L')"""
        )
    def test_stock_incluye_movimientos_cerezos(self):
        self.conn.execute(
            """INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (1,'Ingreso',50,'2026-01-02','Cerezos',500,'L')"""
        )
        st = espino_bodega._stock_cc(self.conn, 1)
        self.assertAlmostEqual(st, 150.0)

    @patch("demo_web.services.native.espino_bodega.is_espino_tenant", return_value=True)
    def test_sync_refleja_stock_cc(self, _mock_espino):
        espino_bodega._sync_inventario_stock(self.conn, 1)
        st = self.conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(float(st), 100.0)

    @patch("demo_web.services.native.espino_bodega.is_espino_tenant", return_value=True)
    def test_salida_devuelve_mov_id_y_sync(self, _mock_espino):
        demo = DemoStub()
        ok, _name, mov_id = espino_bodega.registrar_salida_bodega(
            demo, self.conn, 5.0, producto="PIRIPROXIFEN", fecha="2026-02-01",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(mov_id)
        st = self.conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        self.assertAlmostEqual(float(st), 95.0)


if __name__ == "__main__":
    unittest.main()
