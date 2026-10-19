"""Sidebar: contadores Petróleo / Maquinaria / Riego."""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from demo_web.services.sidebar_badges import (
    MODULOS_BADGE,
    _label_with_count,
    contar_pendientes_modulo,
    conteos_sidebar,
)


class TestSidebarBadges(unittest.TestCase):
    def test_label_with_count(self) -> None:
        self.assertEqual(_label_with_count("Petróleo", 0), "Petróleo")
        self.assertEqual(_label_with_count("Petróleo (3)", 2), "Petróleo (2)")

    def test_conteos_sidebar_solo_modulos_en_menu(self) -> None:
        conn = sqlite3.connect(":memory:")
        with patch(
            "demo_web.services.sidebar_badges.contar_pendientes_modulo",
            side_effect=lambda _c, k: {"Petróleo": 2, "Maquinaria": 0, "Riego": 1}.get(k, 0),
        ):
            out = conteos_sidebar(conn, {"Petróleo", "Riego"})
        self.assertEqual(out, {"Petróleo": 2, "Riego": 1})

    def test_petroleo_pendientes_sql(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE petroleo_bitacora (
                id INTEGER PRIMARY KEY, estado TEXT)"""
        )
        conn.execute("INSERT INTO petroleo_bitacora (estado) VALUES ('pendiente')")
        conn.execute("INSERT INTO petroleo_bitacora (estado) VALUES ('autorizado')")
        conn.commit()
        with patch("demo_web.services.salida_petroleo.habilitado", return_value=True):
            with patch("demo_web.services.salida_petroleo.migrar_tabla"):
                n = contar_pendientes_modulo(conn, "Petróleo")
        self.assertEqual(n, 1)

    def test_modulos_badge_keys(self) -> None:
        self.assertIn("Petróleo", MODULOS_BADGE)
        self.assertIn("Maquinaria", MODULOS_BADGE)
        self.assertIn("Riego", MODULOS_BADGE)


if __name__ == "__main__":
    unittest.main()
