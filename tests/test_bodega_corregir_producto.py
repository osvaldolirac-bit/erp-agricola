"""Corregir un producto de bodega acepta el punto que envía el formulario."""
from __future__ import annotations

import sqlite3
import unittest

from flask import Flask

from demo_web.services.native._helpers import parse_numero_form
from demo_web.services.native.bodega import _post_corregir_stock


class _Demo:
    CLAVE_MAESTRA = "secreta"
    DEFAULT_UNIDAD_INSUMO = "lt"

    def es_admin(self):
        return True

    def requiere_autorizacion_pppl(self, _familia):
        return False

    def registrar_accion(self, _accion, _detalle):
        return None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE inventario (
            id INTEGER PRIMARY KEY,
            producto TEXT,
            familia TEXT,
            stock REAL,
            unidad_medida TEXT,
            precio_medio REAL,
            ingrediente_activo TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO inventario VALUES (127, 'KABUTO', 'ACARICIDA', 2.0, 'lt', 93488.5, 'Hexitiazox')"
    )
    return conn


class TestCorregirProductoBodega(unittest.TestCase):
    def test_el_punto_del_input_numerico_es_valido(self):
        self.assertEqual(parse_numero_form("2.5", None), 2.5)
        self.assertEqual(parse_numero_form("93488.5", None), 93488.5)
        self.assertEqual(parse_numero_form("2,5", None), 2.5)
        self.assertEqual(parse_numero_form("1.250.000", None), 1_250_000.0)
        self.assertIsNone(parse_numero_form("abc", None))

    def test_guardar_stock_y_pmp_con_punto_decimal(self):
        app = Flask(__name__)
        conn = _conn()
        with app.test_request_context(
            "/bodega",
            method="POST",
            data={
                "producto_id": "127",
                "stock": "3.5",
                "precio_medio": "93488.5",
                "nombre": "KABUTO",
                "familia": "ACARICIDA",
                "unidad_medida": "lt",
                "ingrediente_activo": "Hexitiazox",
                "clave_maestra": "secreta",
            },
        ):
            res = _post_corregir_stock(_Demo(), conn)
        self.assertTrue(res["ok"], res["msg"])
        row = conn.execute(
            "SELECT stock, precio_medio, producto FROM inventario WHERE id=127"
        ).fetchone()
        self.assertEqual(row[0], 3.5)
        self.assertEqual(row[1], 93488.5)
        self.assertEqual(row[2], "KABUTO")


if __name__ == "__main__":
    unittest.main()
