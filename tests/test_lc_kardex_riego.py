"""Kardex LC: la salida de fertirriego dice Hydra, link o manual, no salida manual."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime

from demo_web.services.bodega_kardex import _build_kardex_rows


class _Demo:
    DEFAULT_UNIDAD_INSUMO = "kg"
    CENTROS_COSTO = ["CEREZOS CORTE 1", "CIRUELOS"]
    TEMPORADAS_COSTOS = [
        ("2026-2027", datetime(2026, 5, 1).date(), datetime(2027, 4, 30).date()),
    ]

    def f_cantidad(self, x):
        return f"{float(x):.1f}"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE riego (
            id INTEGER PRIMARY KEY, codigo TEXT, fecha TEXT, huerto TEXT, origen TEXT)"""
    )
    conn.execute(
        """CREATE TABLE riego_fertilizantes (
            id INTEGER PRIMARY KEY, codigo TEXT, producto_id INTEGER, cantidad REAL)"""
    )
    conn.execute(
        "INSERT INTO riego VALUES (14, 'RIE-14', '2026-10-15', 'CEREZOS CORTE 1', 'hydrawise')"
    )
    conn.execute(
        "INSERT INTO riego VALUES (15, 'RIE-15', '2026-10-19', 'CIRUELOS', 'manual')"
    )
    conn.execute(
        "INSERT INTO riego VALUES (9, 'RIE-09', '2026-10-05', 'CEREZOS CORTE 1', 'link')"
    )
    conn.execute(
        "INSERT INTO riego_fertilizantes VALUES (1, 'RIE-14', 39, 85)"
    )
    conn.execute(
        "INSERT INTO riego_fertilizantes VALUES (2, 'RIE-15', 39, 350)"
    )
    conn.execute(
        "INSERT INTO riego_fertilizantes VALUES (3, 'RIE-09', 39, 40)"
    )
    return conn


class TestKardexRiego(unittest.TestCase):
    def test_hydra_manual_y_link_no_dicen_salida_manual(self):
        rows = _build_kardex_rows(
            _Demo(),
            _conn(),
            39,
            "NITRATO DE CALCIO",
            [
                (103, "Salida", 85.0, "2026-10-15", "CEREZOS CORTE 1"),
                (155, "Salida", 350.0, "2026-10-19", "CIRUELOS"),
                (90, "Salida", 40.0, "2026-10-05", "CEREZOS CORTE 1"),
                (200, "Salida", 10.0, "2026-10-20", "CIRUELOS"),
            ],
            [],
            {"CEREZOS CORTE 1", "CIRUELOS"},
        )
        origen = {r["id"]: r["origen"] for r in rows}
        self.assertEqual(origen[103], "Riego Hydra RIE-14")
        self.assertEqual(origen[155], "Riego manual RIE-15")
        self.assertEqual(origen[90], "Riego link RIE-09")
        self.assertEqual(origen[200], "Salida manual → CIRUELOS")

    def test_dos_riegos_iguales_no_comparten_linea(self):
        conn = _conn()
        conn.execute(
            "INSERT INTO riego VALUES (16, 'RIE-16', '2026-10-15', 'CEREZOS CORTE 1', 'hydrawise')"
        )
        conn.execute(
            "INSERT INTO riego_fertilizantes VALUES (4, 'RIE-16', 39, 85)"
        )
        rows = _build_kardex_rows(
            _Demo(),
            conn,
            39,
            "NITRATO DE CALCIO",
            [
                (1, "Salida", 85.0, "2026-10-15", "CEREZOS CORTE 1"),
                (2, "Salida", 85.0, "2026-10-15", "CEREZOS CORTE 1"),
            ],
            [],
            {"CEREZOS CORTE 1"},
        )
        self.assertEqual(
            [r["origen"] for r in rows],
            ["Riego Hydra RIE-14", "Riego Hydra RIE-16"],
        )


if __name__ == "__main__":
    unittest.main()
