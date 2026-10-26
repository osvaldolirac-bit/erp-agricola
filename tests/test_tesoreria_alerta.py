"""Aviso de vencimiento de Tesorería: el mismo día, desde las 07:00, una sola vez."""
from __future__ import annotations

import importlib.util
import sqlite3
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from demo_web.services.tesoreria_alerta import (
    armar_correo,
    documentos_por_vencer,
    formato_peso,
    marcar_avisados,
)


HOY = date(2026, 10, 23)
HOY_ISO = "2026-10-23"
CHILE = ZoneInfo("America/Santiago")


def _script_alerta():
    path = Path(__file__).resolve().parents[1] / "scripts" / "alerta_tesoreria_vencimiento.py"
    spec = importlib.util.spec_from_file_location("alerta_tesoreria_vencimiento", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    def test_solo_el_mismo_dia_con_saldo(self):
        conn = _conn()
        _doc(conn, "100", HOY_ISO, total=1500, pagado=500)
        _doc(conn, "101", "2026-10-22")
        _doc(conn, "102", "2026-10-24")
        _doc(conn, "103", HOY_ISO, estado="Pagado")
        _doc(conn, "104", HOY_ISO, total=1000, pagado=1000)
        _doc(conn, "105_P", HOY_ISO, total=80)
        _doc(conn, "GE-9", HOY_ISO)
        _doc(conn, "INT-1", HOY_ISO, total=200, pagado=50, razon="El Espino")
        docs = documentos_por_vencer(conn, HOY)
        numeros = [d["nro_documento"] for d in docs]
        self.assertEqual(numeros, ["100", "INT-1"])
        self.assertEqual(docs[0]["saldo"], 1000)
        self.assertEqual(docs[1]["saldo"], 150)

    def test_la_concepcion_no_avisa_razon_el_espino(self):
        conn = _conn()
        _doc(conn, "200", HOY_ISO, razon="El Espino")
        _doc(conn, "201", HOY_ISO, razon="La Concepción")
        docs = documentos_por_vencer(conn, HOY, excluir_razon_social="El Espino")
        self.assertEqual([d["nro_documento"] for d in docs], ["201"])

    def test_el_espino_conserva_su_razon_social(self):
        conn = _conn()
        _doc(conn, "300", HOY_ISO, razon="El Espino")
        docs = documentos_por_vencer(conn, HOY, excluir_razon_social=None)
        self.assertEqual([d["nro_documento"] for d in docs], ["300"])

    def test_no_repite_un_documento_ya_avisado(self):
        conn = _conn()
        _doc(conn, "400", HOY_ISO)
        primero = documentos_por_vencer(conn, HOY)
        self.assertEqual(len(primero), 1)
        marcar_avisados(conn, primero, "2026-10-23 07:00:00")
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
                    "fecha_vencimiento": HOY_ISO,
                    "saldo": 1250000,
                }
            ],
        )
        self.assertIn("Vence hoy: 1 documento", asunto)
        self.assertIn("7788", html)
        self.assertIn("Hoy", html)
        self.assertIn("$1.250.000", html)
        self.assertIn("23-10-2026", html)
        self.assertEqual(formato_peso(1250000), "$1.250.000")

    def test_el_envio_parte_a_las_siete(self):
        job = _script_alerta()
        self.assertEqual(job.HORA_ENVIO, 7)
        self.assertFalse(job._dentro_de_horario(datetime(2026, 10, 26, 6, 59, tzinfo=CHILE)))
        self.assertTrue(job._dentro_de_horario(datetime(2026, 10, 26, 7, 0, tzinfo=CHILE)))


if __name__ == "__main__":
    unittest.main()
