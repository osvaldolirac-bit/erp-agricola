"""Pagos extras de Remuneraciones suman en la proyección del mes."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.remuneracion_extra import (
    agregar,
    eliminar,
    listar,
    proyeccion,
    total_trabajador,
)


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestRemuneracionExtra(unittest.TestCase):
    def test_la_aplicacion_domingo_suma_en_la_proyeccion(self):
        conn = _conn()
        ok, _msg = agregar(conn, 11, "10", 2026, 40000, "Aplicación domingo")
        self.assertTrue(ok)
        ok, msg = agregar(conn, 11, "10", 2026, 0, "Sin monto")
        self.assertFalse(ok)
        self.assertIn("mayor a cero", msg)
        ok, msg = agregar(conn, 11, "10", 2026, 10000, "  ")
        self.assertFalse(ok)
        self.assertIn("nota", msg)

        base = max(0, 800000 - 160000 - 50000)
        extras = total_trabajador(conn, 11, "10", 2026)
        self.assertEqual(extras, 40000)
        self.assertEqual(proyeccion(base, extras), 630000)
        lineas = listar(conn, "10", 2026, 11)
        self.assertEqual(lineas[0]["nota"], "Aplicación domingo")
        self.assertEqual(listar(conn, "09", 2026, 11), [])

        ok, _msg = eliminar(conn, lineas[0]["id"], "10", 2026)
        self.assertTrue(ok)
        self.assertEqual(total_trabajador(conn, 11, "10", 2026), 0)
        self.assertEqual(proyeccion(base, 0), 590000)


class TestMontoPeso(unittest.TestCase):
    def test_el_formulario_lee_el_mismo_formato_que_el_pago_extra(self):
        from demo_web.services.native.rrhh import _parse_monto_form

        self.assertEqual(_parse_monto_form("$40.000"), 40000)
        self.assertEqual(_parse_monto_form("$1.234.567"), 1234567)
        self.assertEqual(_parse_monto_form("800000"), 800000)
        self.assertEqual(_parse_monto_form(""), 0)


if __name__ == "__main__":
    unittest.main()
