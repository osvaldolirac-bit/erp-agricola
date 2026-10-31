"""Sidebar LC: pastillas de riego regando, en cola y por autorizar."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_web.services.sidebar_badges import avisos_riego_sidebar

ROOT = Path(__file__).resolve().parents[1]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE hydrawise_cola (
               id INTEGER PRIMARY KEY,
               estado TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE hydrawise_cola_item (
               id INTEGER PRIMARY KEY,
               cola_id INTEGER,
               estado TEXT
           )"""
    )
    conn.execute(
        """INSERT INTO hydrawise_cola (id, estado) VALUES (1, 'en_ejecucion')"""
    )
    conn.executemany(
        "INSERT INTO hydrawise_cola_item (cola_id, estado) VALUES (1, ?)",
        [("corriendo",), ("corriendo",), ("corriendo",), ("pendiente",), ("pendiente",)],
    )
    conn.execute(
        """INSERT INTO hydrawise_cola (id, estado) VALUES (2, 'programado')"""
    )
    conn.execute(
        "INSERT INTO hydrawise_cola_item (cola_id, estado) VALUES (2, 'pausado')"
    )
    conn.execute(
        """INSERT INTO hydrawise_cola (id, estado) VALUES (9, 'cerrada')"""
    )
    conn.execute(
        "INSERT INTO hydrawise_cola_item (cola_id, estado) VALUES (9, 'corriendo')"
    )
    return conn


class SidebarRiegoAvisosTests(unittest.TestCase):
    def test_el_espino_no_usa_pastillas(self):
        with patch(
            "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=False
        ):
            self.assertEqual(avisos_riego_sidebar(_conn()), [])

    def test_colores_y_textos(self):
        with (
            patch(
                "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True
            ),
            patch(
                "demo_web.services.sidebar_badges._n_autorizar_riego", return_value=1
            ),
        ):
            avisos = avisos_riego_sidebar(_conn())
        self.assertEqual(
            [(a["tipo"], a["texto"], a["clase"]) for a in avisos],
            [
                ("regando", "3 S regando", "nav-riego-run"),
                ("pausa", "1 S en pausa", "nav-riego-run"),
                ("cola", "2 S en cola", "nav-riego-cola"),
                ("autorizar", "1 autorizar", "nav-riego-auth"),
            ],
        )

    def test_sin_cola_solo_autorizar(self):
        conn = sqlite3.connect(":memory:")
        with (
            patch(
                "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True
            ),
            patch(
                "demo_web.services.sidebar_badges._n_autorizar_riego", return_value=2
            ),
        ):
            avisos = avisos_riego_sidebar(conn)
        self.assertEqual(avisos[0]["texto"], "2 autorizar")
        self.assertEqual(len(avisos), 1)

    def test_menu_y_dashboard(self):
        html = (ROOT / "demo_web/templates/base.html").read_text(encoding="utf-8")
        dash = (ROOT / "demo_web/templates/dashboard/index.html").read_text(encoding="utf-8")
        css = (ROOT / "demo_web/static/css/erp.css").read_text(encoding="utf-8")
        self.assertIn("nav-riego-chip", html)
        self.assertIn("item.riego_avisos", html)
        self.assertNotIn("alertas_riego", dash)
        self.assertIn(".nav-riego-run", css)
        self.assertIn(".nav-riego-cola", css)
        self.assertIn(".nav-riego-auth", css)
        menu = (ROOT / "demo_web/auth/decorators.py").read_text(encoding="utf-8")
        self.assertIn('item["riego_avisos"]', menu)


if __name__ == "__main__":
    unittest.main()
