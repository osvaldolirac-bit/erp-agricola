"""Corregir la cantidad de un insumo deja el mismo número en bodega."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.espino_compras_kardex import aplicar_cantidades_insumo_en_bodega


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE inventario (
            id INTEGER PRIMARY KEY,
            producto TEXT,
            stock REAL,
            precio_medio REAL,
            unidad_medida TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY,
            producto_id INTEGER,
            tipo TEXT,
            cantidad REAL,
            fecha TEXT,
            valor_imputado REAL,
            centro_costo TEXT,
            unidad_medida TEXT
        )"""
    )
    return conn


class TestCantidadInsumoBodega(unittest.TestCase):
    def test_lc_la_diferencia_entra_al_stock_y_al_ingreso(self):
        conn = _conn()
        conn.execute(
            "INSERT INTO inventario VALUES (95, 'EVOLUTION FIFTY', 70, 100, 'lt')"
        )
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (154, 95, 'Ingreso', 40, '2026-10-20', 400, 'BODEGA', 'lt')"""
        )
        concepto, avisos = aplicar_cantidades_insumo_en_bodega(
            conn,
            concepto="[40.0 lt x EVOLUTION FIFTY]",
            fecha_old="2026-10-20",
            fecha_new="2026-10-20",
            cantidades=[50],
            stock_desde_kardex=False,
        )
        stock = conn.execute("SELECT stock FROM inventario WHERE id=95").fetchone()[0]
        mov = conn.execute(
            "SELECT cantidad, valor_imputado, fecha FROM movimientos WHERE id=154"
        ).fetchone()
        self.assertEqual(concepto, "[50.0 lt x EVOLUTION FIFTY]")
        self.assertEqual(stock, 80)
        self.assertEqual(mov[0], 50)
        self.assertEqual(mov[1], 500)
        self.assertIn("40.0 → 50.0 lt", avisos[0])
        self.assertIn("80.0", avisos[0])

    def test_baja_la_cantidad_resta_el_stock(self):
        conn = _conn()
        conn.execute("INSERT INTO inventario VALUES (1, 'EXIREL', 10, 1, 'lt')")
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (1, 1, 'Ingreso', 3, '2026-10-05', 90, 'BODEGA', 'lt')"""
        )
        aplicar_cantidades_insumo_en_bodega(
            conn,
            concepto="[3.0 lt x EXIREL]",
            fecha_old="2026-10-05",
            fecha_new="2026-10-05",
            cantidades=[1],
            stock_desde_kardex=False,
        )
        stock = conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0]
        cant, valor = conn.execute(
            "SELECT cantidad, valor_imputado FROM movimientos WHERE id=1"
        ).fetchone()
        self.assertEqual(stock, 8)
        self.assertEqual(cant, 1)
        self.assertEqual(valor, 30)

    def test_solo_cambia_la_linea_editada(self):
        conn = _conn()
        conn.execute("INSERT INTO inventario VALUES (1, 'CENTURION SUPER', 5, 1, 'lt')")
        conn.execute("INSERT INTO inventario VALUES (2, 'RIPPER FULL', 20, 1, 'lt')")
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (1, 1, 'Ingreso', 5, '2026-10-10', 50, 'BODEGA', 'lt')"""
        )
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (2, 2, 'Ingreso', 20, '2026-10-10', 200, 'BODEGA', 'lt')"""
        )
        concepto, avisos = aplicar_cantidades_insumo_en_bodega(
            conn,
            concepto="[5.0 lt x CENTURION SUPER, 20.0 lt x RIPPER FULL]",
            fecha_old="2026-10-10",
            fecha_new="2026-10-10",
            cantidades=[8, 20],
            stock_desde_kardex=False,
        )
        self.assertEqual(concepto, "[8.0 lt x CENTURION SUPER, 20.0 lt x RIPPER FULL]")
        self.assertEqual(conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0], 8)
        self.assertEqual(conn.execute("SELECT stock FROM inventario WHERE id=2").fetchone()[0], 20)
        self.assertEqual(conn.execute("SELECT cantidad FROM movimientos WHERE id=2").fetchone()[0], 20)
        self.assertEqual(len(avisos), 1)

    def test_espino_recalcula_el_stock_desde_el_kardex(self):
        conn = _conn()
        conn.execute("INSERT INTO inventario VALUES (1, 'KABUTO', 99, 10, 'lt')")
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (1, 1, 'Ingreso', 2, '2026-10-16', 20, 'EL ESPINO', 'lt')"""
        )
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (2, 1, 'Salida', 0.5, '2026-10-17', 0, 'SANTINA', 'lt')"""
        )
        aplicar_cantidades_insumo_en_bodega(
            conn,
            concepto="[2.0 lt x KABUTO]",
            fecha_old="2026-10-16",
            fecha_new="2026-10-16",
            cantidades=[4],
            stock_desde_kardex=True,
        )
        stock, pmp = conn.execute(
            "SELECT stock, precio_medio FROM inventario WHERE id=1"
        ).fetchone()
        cant, valor = conn.execute(
            "SELECT cantidad, valor_imputado FROM movimientos WHERE id=1"
        ).fetchone()
        self.assertEqual(cant, 4)
        self.assertEqual(valor, 40)
        self.assertEqual(stock, 3.5)
        self.assertEqual(pmp, 10)

    def test_sin_ingreso_unico_no_toca_el_stock_ni_la_cantidad(self):
        conn = _conn()
        conn.execute("INSERT INTO inventario VALUES (1, 'UREA', 100, 1, 'kg')")
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (1, 1, 'Ingreso', 40, '2026-10-01', 10, 'BODEGA', 'kg')"""
        )
        conn.execute(
            """INSERT INTO movimientos
               (id, producto_id, tipo, cantidad, fecha, valor_imputado, centro_costo, unidad_medida)
               VALUES (2, 1, 'Ingreso', 40, '2026-10-01', 10, 'BODEGA', 'kg')"""
        )
        concepto, avisos = aplicar_cantidades_insumo_en_bodega(
            conn,
            concepto="[40.0 kg x UREA]",
            fecha_old="2026-10-01",
            fecha_new="2026-10-01",
            cantidades=[55],
            stock_desde_kardex=False,
        )
        self.assertEqual(concepto, "[40.0 kg x UREA]")
        self.assertEqual(conn.execute("SELECT stock FROM inventario WHERE id=1").fetchone()[0], 100)
        self.assertIn("no cambiaron", avisos[0])

    def test_cantidad_cero_se_rechaza(self):
        conn = _conn()
        with self.assertRaises(ValueError):
            aplicar_cantidades_insumo_en_bodega(
                conn,
                concepto="[40.0 lt x EVOLUTION FIFTY]",
                fecha_old="2026-10-20",
                fecha_new="2026-10-20",
                cantidades=[0],
                stock_desde_kardex=False,
            )


if __name__ == "__main__":
    unittest.main()
