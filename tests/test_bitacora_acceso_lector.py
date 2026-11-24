"""El acceso de un lector se anota aunque su conexión de trabajo sea de solo lectura."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from demo_web.auth.bitacora_acceso import conn_para_bitacora  # noqa: E402


class _Demo:
    def __init__(self, path: str) -> None:
        self.NOMBRE_DB = path

    def conectar_db(self):
        raise AssertionError("un lector no debe usar conectar_db() para la bitácora")


class BitacoraAccesoLectorTest(unittest.TestCase):
    def test_la_bitacora_escribe_aunque_conectar_db_sea_solo_lectura(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "lc.db")
            db = sqlite3.connect(path)
            db.execute(
                """CREATE TABLE bitacora (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT, accion TEXT, detalle TEXT, fecha_hora TEXT
                )"""
            )
            db.commit()
            db.close()

            solo_lectura = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                solo_lectura.execute(
                    "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                    ("benjamin.suazo@com-pro.cl", "ACCESO", "Sesión Detectada (Flask LC)", "2026-11-24 15:00:00"),
                )
            solo_lectura.close()

            conn = conn_para_bitacora(_Demo(path))
            conn.execute(
                "INSERT INTO bitacora (usuario, accion, detalle, fecha_hora) VALUES (?,?,?,?)",
                ("benjamin.suazo@com-pro.cl", "ACCESO", "Sesión Detectada (Flask LC)", "2026-11-24 15:00:00"),
            )
            conn.commit()
            row = conn.execute(
                "SELECT usuario, accion FROM bitacora WHERE usuario=?",
                ("benjamin.suazo@com-pro.cl",),
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("benjamin.suazo@com-pro.cl", "ACCESO"))
