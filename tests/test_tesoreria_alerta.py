"""Aviso de vencimiento de Tesorería: un día antes y una sola vez."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from demo_web.services.tesoreria_alerta import (
    armar_correo,
    documentos_por_vencer,
    formato_peso,
    marcar_avisados,
)


HOY = date(2026, 10, 23)
MANANA = "2026-10-24"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY,
            nro_documento TEXT,
            proveedor TEXT,
            razon_social TEXT,
            fecha_vencimiento TEXT,
            monto_total REAL,
            monto_pagado REAL,
            estado TEXT
        )"""
    )
    return conn


def _doc(conn, nro, venc, total=1000, pagado=0, estado="Pendiente", razon="La Concepción", proveedor="ACME"):
    conn.execute(
        """INSERT INTO facturas
           (nro_documento, proveedor, razon_social, fecha_vencimiento, monto_total, monto_pagado, estado)
           VALUES (?,?,?,?,?,?,?)""",
        (nro, proveedor, razon, venc, total, pagado, estado),
    )


class TestTesoreriaAlerta(unittest.TestCase):
    def test_solo_el_dia_siguiente_con_saldo(self):
        conn = _conn()
        _doc(conn, "100", MANANA, total=1500, pagado=500)
        _doc(conn, "101", "2026-10-23")
        _doc(conn, "102", "2026-10-25")
        _doc(conn, "103", MANANA, estado="Pagado")
        _doc(conn, "104", MANANA, total=1000, pagado=1000)
        _doc(conn, "105_P", MANANA, total=80)
        _doc(conn, "GE-9", MANANA)
        _doc(conn, "INT-1", MANANA, total=200, pagado=50, razon="El Espino")
        docs = documentos_por_vencer(conn, HOY)
        numeros = [d["nro_documento"] for d in docs]
        self.assertEqual(numeros, ["100", "INT-1"])
        self.assertEqual(docs[0]["saldo"], 1000)
        self.assertEqual(docs[1]["saldo"], 150)

    def test_la_concepcion_no_avisa_razon_el_espino(self):
        conn = _conn()
        _doc(conn, "200", MANANA, razon="El Espino")
        _doc(conn, "201", MANANA, razon="La Concepción")
        docs = documentos_por_vencer(conn, HOY, excluir_razon_social="El Espino")
        self.assertEqual([d["nro_documento"] for d in docs], ["201"])

    def test_el_espino_conserva_su_razon_social(self):
        conn = _conn()
        _doc(conn, "300", MANANA, razon="El Espino")
        docs = documentos_por_vencer(conn, HOY, excluir_razon_social=None)
        self.assertEqual([d["nro_documento"] for d in docs], ["300"])

    def test_no_repite_un_documento_ya_avisado(self):
        conn = _conn()
        _doc(conn, "400", MANANA)
        primero = documentos_por_vencer(conn, HOY)
        self.assertEqual(len(primero), 1)
        marcar_avisados(conn, primero, "2026-10-23 08:05:00")
        conn.commit()
        self.assertEqual(documentos_por_vencer(conn, HOY), [])

    def test_correo_lleva_saldo_y_documento(self):
        asunto, html = armar_correo(
            "ERP Agrícola La Concepción",
            [
                {
                    "id": 1,
                    "nro_documento": "7788",
                    "proveedor": "Proveedor Uno",
                    "razon_social": "La Concepción",
                    "fecha_vencimiento": MANANA,
                    "saldo": 1250000,
                }
            ],
        )
        self.assertIn("1 documento", asunto)
        self.assertIn("7788", html)
        self.assertIn("$1.250.000", html)
        self.assertIn("24-10-2026", html)
        self.assertEqual(formato_peso(1250000), "$1.250.000")


if __name__ == "__main__":
    unittest.main()
