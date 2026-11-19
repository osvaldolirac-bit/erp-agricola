"""Registrar trabajo de El Espino ofrece toda la maestra activa, no solo TRAC."""
from __future__ import annotations

import sqlite3
import sys
import types
import unittest
from datetime import date, datetime

from flask import Flask

if "erp_solo_lectura" not in sys.modules:
    _solo = types.ModuleType("erp_solo_lectura")
    _solo.conn_en_solo_lectura = lambda conn: False
    sys.modules["erp_solo_lectura"] = _solo

if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.ModuleType("streamlit")

from demo_web.services.native.espino_maquinaria import _select_maquinaria, gather_maquinaria


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE bitacora_maquinaria (
            id INTEGER PRIMARY KEY, id_maquinaria TEXT
        )"""
    )
    conn.execute("CREATE TABLE petroleo (id INTEGER PRIMARY KEY, vehiculo TEXT)")
    conn.execute(
        "CREATE TABLE libro_campo (id INTEGER PRIMARY KEY, maquina TEXT, tractor TEXT)"
    )
    conn.execute(
        """CREATE TABLE trabajos_maquinaria_espino (
            id INTEGER PRIMARY KEY,
            fecha TEXT, documento TEXT, tractor TEXT, implemento TEXT,
            trabajo TEXT, horas REAL, hectareas REAL,
            monto_tractor REAL, monto_implemento REAL, monto REAL
        )"""
    )
    conn.execute(
        """CREATE TABLE trabajos_maquinaria_espino_mov (
            id INTEGER PRIMARY KEY,
            fecha TEXT, documento TEXT, detalle TEXT, tipo_mov TEXT, haber REAL
        )"""
    )
    return conn


class _Demo:
    def hora_chile(self):
        return datetime(2026, 11, 19)

    @staticmethod
    def f_peso(n):
        return str(n)


class TestTrabajoMaquinaria(unittest.TestCase):
    def test_el_trabajo_lista_camion_y_tractor(self):
        conn = _conn()
        try:
            _select_maquinaria(conn)
            conn.execute(
                """INSERT INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden)
                   VALUES ('CAM-09', 'Camión fundo', 'Camión', 1, 50)"""
            )
            conn.execute(
                "UPDATE maestra_maquinaria SET activo=0 WHERE codigo='TRAC-CHINO'"
            )
            conn.commit()
            app = Flask(__name__)
            with app.test_request_context("/?op=trabajo"):
                ctx = gather_maquinaria(
                    _Demo(), conn, date(2026, 1, 1), date(2026, 12, 31), "2026"
                )
            codigos = {m["codigo"] for m in ctx["tractores"]}
            self.assertIn("CAM-09", codigos)
            self.assertIn("TRAC-MF", codigos)
            self.assertNotIn("TRAC-CHINO", codigos)
        finally:
            conn.close()
