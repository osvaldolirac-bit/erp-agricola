"""Cuenta de mano de obra del contratista, aparte del abono del cliente."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "riomaipo_vps"))

from rmweb import core  # noqa: E402


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE cotizaciones (
            id INTEGER PRIMARY KEY,
            estado TEXT,
            contratista_id INTEGER,
            folio TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE cotizacion_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cotizacion_id INTEGER,
            descripcion TEXT,
            obs TEXT,
            unidad TEXT,
            cantidad REAL,
            precio_unitario REAL,
            total REAL,
            orden INTEGER
        )
        """
    )
    return db


class ManoObraContratistaTest(unittest.TestCase):
    def test_reconoce_la_partida_mo(self) -> None:
        self.assertTrue(core.es_linea_mo("MO"))
        self.assertTrue(core.es_linea_mo("mano de obra"))
        self.assertTrue(core.es_linea_mo("M.O."))
        self.assertTrue(core.es_linea_mo("MO Y CONEXION A CAMARA EXISTENTE"))
        self.assertFalse(core.es_linea_mo("materiales"))
        self.assertFalse(core.es_linea_mo("MADERA"))

    def test_cuenta_aparte_y_abono_no_toca_al_cliente(self) -> None:
        db = _db()
        db.execute("INSERT INTO cotizaciones (id, estado, folio) VALUES (1, 'borrador', 'COT-30_2026')")
        filas = [
            ("MADERA", "30,5 M2", 0, 0),
            ("materiales", "lija", 55000, 55000),
            ("MO", "2 manos", 4500, 135225),
            ("VIGAS FIERRO", "19.07 M2", 0, 0),
            ("MO", "2 manos", 8000, 152560),
            ("CORTA GOTA", "54,5 ML", 0, 0),
            ("MO", "instalacion y pintura", 4000, 218000),
        ]
        for i, (desc, obs, pu, tot) in enumerate(filas, start=1):
            cant = 1 if not pu else tot / pu
            db.execute(
                """
                INSERT INTO cotizacion_items
                (cotizacion_id, descripcion, obs, unidad, cantidad, precio_unitario, total, orden)
                VALUES (1,?,?, 'un', ?,?,?,?)
                """,
                (desc, obs, cant, pu, tot, i),
            )
        items = db.execute("SELECT * FROM cotizacion_items ORDER BY orden").fetchall()
        self.assertEqual(core.monto_mo(items), 505785)
        self.assertEqual(
            [ln["partida"] for ln in core.lineas_mo_detalle(items)],
            ["MADERA", "VIGAS FIERRO", "CORTA GOTA"],
        )

        core.refrescar_cuenta_mo(db, 1)
        self.assertIsNone(db.execute("SELECT id FROM cuentas_mo").fetchone())
        ok, err = core.registrar_abono_mo(db, 1, "2026-11-23", 100000, "Transferencia", None)
        self.assertFalse(ok)
        self.assertIn("aprobar", err)

        ok, err = core.asignar_contratista_cotizacion(db, 1, None, "Juan Pérez")
        self.assertTrue(ok, err)
        db.execute("UPDATE cotizaciones SET estado='aprobada' WHERE id=1")
        core.refrescar_cuenta_mo(db, 1)
        cuenta = db.execute("SELECT * FROM cuentas_mo WHERE cotizacion_id=1").fetchone()
        self.assertEqual(cuenta["monto"], 505785)
        self.assertEqual(cuenta["saldo"], 505785)
        self.assertEqual(cuenta["estado"], "pendiente")

        ok, err = core.registrar_abono_mo(db, 1, "2026-11-23", 200000, "Transferencia", "anticipo")
        self.assertTrue(ok, err)
        cuenta = db.execute("SELECT * FROM cuentas_mo WHERE cotizacion_id=1").fetchone()
        self.assertEqual(cuenta["abonado"], 200000)
        self.assertEqual(cuenta["saldo"], 305785)
        self.assertEqual(cuenta["estado"], "parcial")

        db.execute(
            """
            UPDATE cotizacion_items
            SET total=100000, precio_unitario=100000
            WHERE descripcion='MO' AND total=135225
            """
        )
        core.refrescar_cuenta_mo(db, 1)
        cuenta = db.execute("SELECT * FROM cuentas_mo WHERE cotizacion_id=1").fetchone()
        self.assertEqual(cuenta["monto"], 470560)
        self.assertEqual(cuenta["abonado"], 200000)
        self.assertEqual(cuenta["saldo"], 270560)

        ok, err = core.registrar_abono_mo(db, 1, "2026-11-24", 9999999, "Efectivo", None)
        self.assertFalse(ok)
        self.assertIsNone(
            db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='abonos'").fetchone()
        )
