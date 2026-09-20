#!/usr/bin/env python3
"""Tests pago Tesorería: proveedor desde doc_ids, no hidden field stale."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TesoreriaProveedorPagoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE facturas (
                id INTEGER PRIMARY KEY,
                nro_documento TEXT,
                proveedor TEXT,
                razon_social TEXT,
                estado TEXT,
                monto_total REAL,
                monto_pagado REAL DEFAULT 0,
                fecha_vencimiento TEXT
            );
            INSERT INTO facturas VALUES
              (1, 'D-1', 'Duilio Pruzzo', 'El Espino', 'Pagado', 100, 100, '2026-01-01'),
              (2, 'F-762531', 'FERMACO', 'El Espino', 'Pendiente', 500000, 0, '2026-02-01');
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_proveedor_desde_ids_fermaco(self) -> None:
        from demo_web.services.native import tesoreria as t

        prov, err = t._proveedor_unico_desde_ids(self.conn, [2])
        self.assertIsNone(err)
        self.assertEqual(prov, "FERMACO")

    def test_proveedor_desde_ids_pagado_falla(self) -> None:
        from demo_web.services.native import tesoreria as t

        prov, err = t._proveedor_unico_desde_ids(self.conn, [1])
        self.assertIsNone(prov)
        self.assertIn("pagados", err or "")

    def test_branding_bundled_logo(self) -> None:
        from demo_web.services.branding import find_master_logo_path

        path = find_master_logo_path()
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    raise SystemExit(unittest.main())
