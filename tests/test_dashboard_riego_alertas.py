"""Dashboard LC: avisos de riego en ejecución, en cola y para autorizar."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_web.services.dashboard import alertas_riego_dashboard

ROOT = Path(__file__).resolve().parents[1]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE hydrawise_cola (
               id INTEGER PRIMARY KEY,
               tipo TEXT,
               inicio_programa TEXT,
               estado TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE hydrawise_cola_item (
               id INTEGER PRIMARY KEY,
               cola_id INTEGER,
               orden INTEGER,
               relay_id INTEGER,
               minutos REAL,
               estado TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE hydrawise_zona (
               relay_id INTEGER PRIMARY KEY,
               nombre_hw TEXT,
               alias TEXT,
               huerto_cc TEXT
           )"""
    )
    conn.execute(
        """INSERT INTO hydrawise_zona (relay_id, nombre_hw, alias, huerto_cc)
           VALUES (1, 'Sector 1 Cerezo', 'corte 1', 'CEREZOS CORTE 1')"""
    )
    conn.execute(
        """INSERT INTO hydrawise_zona (relay_id, nombre_hw, alias, huerto_cc)
           VALUES (2, 'Sector 4 Nogale', 'corte 4', 'NOGALES APARICION')"""
    )
    return conn


class DashboardRiegoAlertasTests(unittest.TestCase):
    def test_el_espino_no_muestra_avisos(self):
        conn = _conn()
        conn.execute(
            """INSERT INTO hydrawise_cola (id, tipo, inicio_programa, estado)
               VALUES (1, 'run_now', '2026-10-31 06:51:54', 'en_ejecucion')"""
        )
        conn.execute(
            """INSERT INTO hydrawise_cola_item (cola_id, orden, relay_id, minutos, estado)
               VALUES (1, 1, 1, 180, 'corriendo')"""
        )
        with patch(
            "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=False
        ):
            self.assertEqual(alertas_riego_dashboard(conn), [])

    def test_ejecucion_cola_y_autorizar(self):
        conn = _conn()
        conn.execute(
            """INSERT INTO hydrawise_cola (id, tipo, inicio_programa, estado)
               VALUES (1, 'run_now', '2026-10-31 06:51:54', 'en_ejecucion')"""
        )
        conn.executemany(
            """INSERT INTO hydrawise_cola_item (cola_id, orden, relay_id, minutos, estado)
               VALUES (1, ?, ?, ?, ?)""",
            [
                (1, 1, 180, "corriendo"),
                (2, 2, 90, "pendiente"),
            ],
        )
        with (
            patch(
                "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True
            ),
            patch(
                "demo_web.services.dashboard._pendientes_autorizar", return_value=2
            ),
        ):
            avisos = alertas_riego_dashboard(conn)
        self.assertEqual([a["tipo"] for a in avisos], ["ejecucion", "cola", "autorizar"])
        self.assertIn("Riego en ejecución", avisos[0]["texto"])
        self.assertIn("Sector 1 Cerezo — corte 1", avisos[0]["texto"])
        self.assertIn("CEREZOS CORTE 1", avisos[0]["texto"])
        self.assertIn("3 h", avisos[0]["texto"])
        self.assertIn("Sector 4 Nogale — corte 4", avisos[1]["texto"])
        self.assertIn("1 h 30 min", avisos[1]["texto"])
        self.assertNotIn("programa", avisos[1]["texto"])
        self.assertEqual(avisos[2]["texto"], "Hay 2 riegos pendientes de autorizar.")
        self.assertEqual(avisos[2]["clase"], "dash-alerta-riego-auth")

    def test_pausa_y_programa_futuro(self):
        conn = _conn()
        conn.execute(
            """INSERT INTO hydrawise_cola (id, tipo, inicio_programa, estado)
               VALUES (1, 'programado', '2026-10-31 18:00:00', 'programado')"""
        )
        conn.execute(
            """INSERT INTO hydrawise_cola_item (cola_id, orden, relay_id, minutos, estado)
               VALUES (1, 1, 2, 60, 'pendiente')"""
        )
        with (
            patch(
                "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True
            ),
            patch("demo_web.services.dashboard._pendientes_autorizar", return_value=1),
        ):
            avisos = alertas_riego_dashboard(conn)
        self.assertEqual(avisos[0]["tipo"], "cola")
        self.assertIn("programa 31/10/2026 18:00", avisos[0]["texto"])
        self.assertEqual(avisos[1]["texto"], "Hay 1 riego pendiente de autorizar.")

        conn.execute("UPDATE hydrawise_cola_item SET estado='pausado', relay_id=1, minutos=30")
        with (
            patch(
                "demo_web.services.tenant_scope.is_concepcion_tenant", return_value=True
            ),
            patch("demo_web.services.dashboard._pendientes_autorizar", return_value=0),
        ):
            avisos = alertas_riego_dashboard(conn)
        self.assertEqual([a["tipo"] for a in avisos], ["pausa"])
        self.assertIn("Riego en pausa", avisos[0]["texto"])
        self.assertIn("30 min", avisos[0]["texto"])

    def test_la_plantilla_enlaza_hoy(self):
        html = (ROOT / "demo_web/templates/dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn("alertas_riego", html)
        self.assertIn("sec='hoy'", html)
        self.assertIn("Ver en Hoy", html)
        css = (ROOT / "demo_web/static/css/erp.css").read_text(encoding="utf-8")
        self.assertIn("dash-alerta-riego-run", css)
        self.assertIn("dash-alerta-riego-auth", css)


if __name__ == "__main__":
    unittest.main()
