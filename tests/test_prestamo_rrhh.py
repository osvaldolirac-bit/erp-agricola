"""Libro mayor de préstamos: el crédito pagado no se come al siguiente."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.prestamo_rrhh import (
    actualizar_prestamo,
    descuento_sugerido,
    listar_trabajador,
    migrar_desde_ficha,
    registrar_prestamo,
    saldo_disponible_mes,
    sincronizar_abono_mes,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE remuneraciones_fichas (
            trabajador_id INTEGER PRIMARY KEY,
            sueldo_pactado REAL,
            monto_prestamo REAL,
            cuotas_prestamo INTEGER,
            suple_fijo REAL,
            cuotas_pagadas INTEGER,
            primera_cuota_mes TEXT,
            primera_cuota_anio INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE remuneracion_mes (
            trabajador_id INTEGER,
            mes TEXT,
            anio INTEGER,
            descuento_prestamo REAL,
            PRIMARY KEY (trabajador_id, mes, anio)
        )"""
    )
    return conn


def _ficha(conn, tid, monto, cuotas, mes, anio, sueldo=800000):
    conn.execute(
        """INSERT INTO remuneraciones_fichas
           (trabajador_id, sueldo_pactado, monto_prestamo, cuotas_prestamo, suple_fijo,
            cuotas_pagadas, primera_cuota_mes, primera_cuota_anio)
           VALUES (?, ?, ?, ?, 0, 0, ?, ?)""",
        (tid, sueldo, monto, cuotas, mes, anio),
    )


def _desc(conn, tid, mes, anio, monto):
    conn.execute(
        "INSERT INTO remuneracion_mes (trabajador_id, mes, anio, descuento_prestamo) VALUES (?,?,?,?)",
        (tid, mes, anio, monto),
    )


class TestPrestamoLibro(unittest.TestCase):
    def test_el_prestamo_pagado_no_anula_el_nuevo(self):
        conn = _conn()
        _ficha(conn, 11, 200000, 4, "10", 2026)
        for mes in ("06", "07", "08", "09"):
            _desc(conn, 11, mes, 2026, 50000)
        self.assertEqual(migrar_desde_ficha(conn), 1)
        self.assertEqual(migrar_desde_ficha(conn), 0)

        viejo = listar_trabajador(conn, 11)[0]
        self.assertEqual(viejo["estado"], "saldado")
        self.assertEqual(viejo["saldo"], 0)
        self.assertEqual(viejo["descontado"], 200000)
        self.assertEqual(viejo["primera_cuota_mes"], "06")
        self.assertEqual(viejo["cuotas_pagadas"], 4)

        ok, _msg = registrar_prestamo(conn, 11, 150000, 3, "10", 2026, "2026-10-26")
        self.assertTrue(ok)
        lineas = listar_trabajador(conn, 11)
        self.assertEqual(len(lineas), 2)
        self.assertEqual(lineas[0]["saldo"], 0)
        self.assertEqual(lineas[1]["saldo"], 150000)
        self.assertEqual(lineas[1]["estado"], "vigente")
        self.assertEqual(descuento_sugerido(conn, 11, "10", 2026), 50000)
        self.assertEqual(descuento_sugerido(conn, 11, "06", 2026), 0)
        self.assertEqual(descuento_sugerido(conn, 11, "06", 2026, desc_guardado=50000), 50000)

        sincronizar_abono_mes(conn, 11, "10", 2026, 50000)
        lineas = listar_trabajador(conn, 11)
        self.assertEqual(lineas[0]["descontado"], 200000)
        self.assertEqual(lineas[1]["descontado"], 50000)
        self.assertEqual(lineas[1]["saldo"], 100000)
        self.assertEqual(saldo_disponible_mes(conn, 11, "06", 2026), 50000)
        self.assertEqual(saldo_disponible_mes(conn, 11, "10", 2026), 150000)

        ok, msg = actualizar_prestamo(conn, lineas[1]["id"], 40000, 3, "10", 2026)
        self.assertFalse(ok)
        self.assertIn("ya descontado", msg)

        ficha = conn.execute(
            "SELECT sueldo_pactado, monto_prestamo, primera_cuota_mes FROM remuneraciones_fichas WHERE trabajador_id=11"
        ).fetchone()
        self.assertEqual(ficha[0], 800000)
        self.assertEqual(ficha[1], 150000)
        self.assertEqual(ficha[2], "10")

    def test_un_credito_abierto_conserva_su_primera_cuota(self):
        conn = _conn()
        _ficha(conn, 16, 150000, 5, "08", 2026, sueldo=600000)
        _desc(conn, 16, "08", 2026, 30000)
        _desc(conn, 16, "09", 2026, 30000)
        migrar_desde_ficha(conn)
        linea = listar_trabajador(conn, 16)[0]
        self.assertEqual(linea["estado"], "vigente")
        self.assertEqual(linea["saldo"], 90000)
        self.assertEqual(linea["cuotas_pagadas"], 2)
        self.assertEqual(linea["primera_cuota_mes"], "08")
        self.assertEqual(descuento_sugerido(conn, 16, "10", 2026), 30000)


if __name__ == "__main__":
    unittest.main()
