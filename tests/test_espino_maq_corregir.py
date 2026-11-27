"""Corrección de una aplicación en gastos de maquinaria El Espino."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date, datetime

from flask import Flask

from demo_web.services.native import espino_maquinaria as maq


class _Demo:
    CLAVE_MAESTRA = "secreta"

    def __init__(self, admin: bool = True) -> None:
        self._admin = admin
        self.acciones: list[str] = []

    def es_solo_lectura(self) -> bool:
        return False

    def es_admin(self) -> bool:
        return self._admin

    def f_peso(self, n) -> str:
        return f"${int(round(float(n))):,}".replace(",", ".")

    def registrar_accion(self, _mod, detalle: str) -> None:
        self.acciones.append(detalle)

    def hora_chile(self) -> datetime:
        return datetime(2026, 11, 26, 12, 0, 0)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE trabajos_maquinaria_espino (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, documento TEXT, maquinaria_codigo TEXT, maquinaria TEXT,
            trabajo TEXT, horas REAL, monto REAL,
            tractor_codigo TEXT, tractor TEXT, implemento_codigo TEXT, implemento TEXT,
            monto_tractor REAL, monto_implemento REAL, hectareas REAL
        )
        """
    )
    conn.execute("CREATE TABLE maestra_maquinaria (codigo TEXT, nombre TEXT)")
    conn.execute("INSERT INTO maestra_maquinaria VALUES ('TRAC-1', 'Same')")
    conn.execute("INSERT INTO maestra_maquinaria VALUES ('IMP-1', 'Rastra')")
    conn.execute(
        """
        INSERT INTO trabajos_maquinaria_espino
            (fecha, documento, maquinaria_codigo, maquinaria, trabajo, horas, monto,
             tractor_codigo, tractor, implemento_codigo, implemento,
             monto_tractor, monto_implemento, hectareas)
        VALUES ('2026-11-20', 'INT-20261120-01', 'TRAC-1', 'TRAC-1 — Same', 'Surcos',
                2, 10000, 'TRAC-1', 'TRAC-1 — Same', '', '', 10000, 0, 1)
        """
    )
    conn.commit()
    return conn


class CorregirAplicacionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.conn = _db()
        self.demo = _Demo()
        self.fi = date(2026, 7, 1)
        self.ff = date(2027, 6, 30)

    def tearDown(self) -> None:
        self.conn.close()

    def _post(self, **data):
        payload = {
            "trabajo_id": "1",
            "fecha": "2026-11-20",
            "sin_doc": "1",
            "documento": "INT-20261120-01",
            "tractor_codigo": "TRAC-1",
            "implemento_codigo": "IMP-1",
            "trabajo": "Surcos corregido",
            "hectareas": "2",
            "horas": "3",
            "monto_tractor": "10000",
            "monto_implemento": "5000",
            "clave_maestra": "secreta",
        }
        payload.update(data)
        with self.app.test_request_context("/", method="POST", data=payload):
            return maq.post_corregir(self.demo, self.conn, self.fi, self.ff)

    def test_recalcula_el_total_de_la_aplicacion(self) -> None:
        res = self._post()
        self.assertTrue(res["ok"], res["msg"])
        self.assertIn("$30.000", res["msg"])
        row = self.conn.execute(
            "SELECT trabajo, horas, hectareas, monto, implemento_codigo, documento FROM trabajos_maquinaria_espino WHERE id=1"
        ).fetchone()
        self.assertEqual(row[0], "Surcos corregido")
        self.assertEqual(row[1], 3)
        self.assertEqual(row[2], 2)
        self.assertEqual(row[3], 30000)
        self.assertEqual(row[4], "IMP-1")
        self.assertEqual(row[5], "INT-20261120-01")

    def test_la_clave_incorrecta_no_cambia_el_registro(self) -> None:
        res = self._post(clave_maestra="no")
        self.assertFalse(res["ok"])
        monto = self.conn.execute("SELECT monto FROM trabajos_maquinaria_espino WHERE id=1").fetchone()[0]
        self.assertEqual(monto, 10000)

    def test_sin_perfil_admin_no_corrige(self) -> None:
        self.demo = _Demo(admin=False)
        res = self._post()
        self.assertFalse(res["ok"])
        self.assertIn("admin", res["msg"])


if __name__ == "__main__":
    unittest.main()
