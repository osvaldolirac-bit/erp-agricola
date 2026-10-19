"""Revertir salidas bodega Espino."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.espino_bodega_desfase import revertir_salidas_lineas_espino


class TestEspinoRevertir(unittest.TestCase):
    def test_dos_lineas_dos_movimientos(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE inventario (id INTEGER PRIMARY KEY, producto TEXT, stock REAL DEFAULT 0);
            CREATE TABLE movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER, tipo TEXT, cantidad REAL, fecha TEXT,
                centro_costo TEXT, valor_imputado REAL, unidad_medida TEXT);
            CREATE TABLE libro_campo (id INTEGER, movimiento_id INTEGER);
            """
        )
        conn.execute("INSERT INTO inventario VALUES (1,'PIRIPROXIFEN')")
        conn.execute(
            """INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (1,'Salida',2,'2026-03-01','EL ESPINO',20,'L')"""
        )
        conn.execute(
            """INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
               VALUES (1,'Salida',3,'2026-03-01','EL ESPINO',30,'L')"""
        )
        rows = [
            {
                "producto": "PIRIPROXIFEN",
                "gasto_total": 2.0,
                "fecha": "2026-03-01",
                "movimiento_id": 1,
            },
            {
                "producto": "PIRIPROXIFEN",
                "gasto_total": 3.0,
                "fecha": "2026-03-01",
                "movimiento_id": 2,
            },
        ]
        rev = revertir_salidas_lineas_espino(conn, rows)
        self.assertEqual(len(rev), 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
