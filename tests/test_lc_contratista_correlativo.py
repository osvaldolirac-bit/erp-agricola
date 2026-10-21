"""Un servicio de contratista (CONTR-) no ocupa correlativo en compras, igual que INT-."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.native.compras import (
    _correlativo_duplicado,
    _es_documento_interno,
    _siguiente_correlativo_interno,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY,
            nro_documento TEXT,
            folio_interno TEXT,
            razon_social TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO facturas VALUES (1, '31025', '5', 'Carlos Lira')"
    )
    conn.execute(
        "INSERT INTO facturas VALUES (2, 'CONTR-20261021-01', '9', 'Carlos Lira')"
    )
    conn.execute(
        "INSERT INTO facturas VALUES (3, 'INT-20261021-01', '8', 'Carlos Lira')"
    )
    return conn


class TestContratistaSinCorrelativo(unittest.TestCase):
    def test_contr_es_documento_interno(self):
        self.assertTrue(_es_documento_interno("CONTR-20261021-01"))
        self.assertTrue(_es_documento_interno("INT-20261021-01"))
        self.assertFalse(_es_documento_interno("31025"))

    def test_el_servicio_no_adelanta_el_correlativo(self):
        conn = _conn()
        self.assertEqual(_siguiente_correlativo_interno(conn, "Carlos Lira"), "6")
        self.assertIsNone(_correlativo_duplicado(conn, "9", "Carlos Lira"))
        self.assertIsNotNone(_correlativo_duplicado(conn, "5", "Carlos Lira"))


if __name__ == "__main__":
    unittest.main()
