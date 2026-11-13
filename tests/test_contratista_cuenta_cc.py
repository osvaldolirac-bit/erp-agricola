"""La cuenta corriente del contratista muestra el CC imputado y el tipo escrito."""
from __future__ import annotations

import sqlite3
import sys
import types
import unittest
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd
from flask import Flask

from demo_web.services.contratista_cuenta import (
    centros_imputados,
    guardar_tipo_trabajo,
    presentar_cuenta,
)
from demo_web.services.native.rrhh import _contratistas_cuenta


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nro_documento TEXT,
            proveedor TEXT,
            monto_total REAL,
            centro_costo TEXT,
            contratista_id INTEGER
        )"""
    )
    conn.execute("CREATE TABLE contratistas (id INTEGER PRIMARY KEY, razon_social TEXT)")
    conn.execute("INSERT INTO contratistas (id, razon_social) VALUES (3, 'HERNAN ARAVENA')")
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, monto_total, centro_costo, contratista_id)
           VALUES ('CONTR-1', 'HERNAN ARAVENA', 1000, NULL, 3)"""
    )
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, monto_total, centro_costo, contratista_id)
           VALUES ('CONTR-1_P', 'HERNAN ARAVENA', 0, 'SWEET ARYANA', 3)"""
    )
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, monto_total, centro_costo, contratista_id)
           VALUES ('CONTR-1_P', 'HERNAN ARAVENA', 0, 'ROYAL DOWN', 3)"""
    )
    conn.execute(
        """INSERT INTO facturas (nro_documento, proveedor, monto_total, centro_costo, contratista_id)
           VALUES ('CONTR-2', 'OTRO', 50, NULL, 9)"""
    )
    return conn


class TestCuentaContratista(unittest.TestCase):
    def test_el_pdf_nombra_los_cc_y_el_tipo_escrito(self):
        conn = _conn()
        self.assertTrue(guardar_tipo_trabajo(conn, "CONTR-1", 3, "  cosecha  a  piso "))
        self.assertFalse(guardar_tipo_trabajo(conn, "CONTR-1_P", 3, "no"))
        self.assertFalse(guardar_tipo_trabajo(conn, "CONTR-2", 3, "ajeno"))
        self.assertEqual(
            conn.execute("SELECT tipo_trabajo FROM facturas WHERE nro_documento='CONTR-1'").fetchone()[0],
            "cosecha a piso",
        )
        self.assertEqual(centros_imputados(conn, ["CONTR-1"]), {"CONTR-1": "SWEET ARYANA, ROYAL DOWN"})

        df = pd.DataFrame(
            [
                {
                    "FECHA": date(2026, 11, 6),
                    "TIPO": "TRABAJO",
                    "DOCUMENTO": "CONTR-1",
                    "DETALLE": "cosecha SA",
                    "DEBE": 1000.0,
                    "HABER": 0.0,
                    "SALDO": 1000.0,
                },
                {
                    "FECHA": date(2026, 11, 8),
                    "TIPO": "PAGO",
                    "DOCUMENTO": "CONTR-1",
                    "DETALLE": "Pago (Transferencia)",
                    "DEBE": 0.0,
                    "HABER": 400.0,
                    "SALDO": 600.0,
                },
            ]
        )
        filas, pdf = presentar_cuenta(conn, df, lambda n: str(n))
        self.assertTrue(filas[0]["es_trabajo"])
        self.assertEqual(filas[0]["tipo_trabajo"], "cosecha a piso")
        self.assertEqual(filas[0]["cc"], "SWEET ARYANA, ROYAL DOWN")
        self.assertFalse(filas[1]["es_trabajo"])
        self.assertEqual(list(pdf.columns), ["FECHA", "TIPO DE TRABAJO", "CC", "DOCUMENTO", "DETALLE", "DEBE", "HABER", "SALDO"])
        self.assertEqual(pdf.iloc[0]["TIPO DE TRABAJO"], "cosecha a piso")
        self.assertEqual(pdf.iloc[0]["CC"], "SWEET ARYANA, ROYAL DOWN")
        self.assertEqual(pdf.iloc[1]["TIPO DE TRABAJO"], "PAGO")
        self.assertEqual(pdf.iloc[1]["CC"], "SWEET ARYANA, ROYAL DOWN")
        self.assertNotIn("TRABAJO", set(pdf["TIPO DE TRABAJO"]))

    def test_sin_tipo_la_columna_queda_en_blanco(self):
        conn = _conn()
        df = pd.DataFrame(
            [{
                "FECHA": "2026-11-06",
                "TIPO": "TRABAJO",
                "DOCUMENTO": "CONTR-1",
                "DETALLE": "cosecha",
                "DEBE": 10,
                "HABER": 0,
                "SALDO": 10,
            }]
        )
        _, pdf = presentar_cuenta(conn, df, str)
        self.assertEqual(pdf.iloc[0]["TIPO DE TRABAJO"], "")
        self.assertEqual(pdf.iloc[0]["CC"], "SWEET ARYANA, ROYAL DOWN")


class _Demo:
    def __init__(self):
        self.CUARTELES_OFICIALES = ["SANTINA"]
        self.pdf = None

    def f_peso(self, n):
        return f"{n}"

    def hora_chile(self):
        return datetime(2026, 11, 12, 12, 0, 0)

    def generar_pdf_blob(self, df, titulo, incluir_precios=False, orden_asc=True):
        self.pdf = df.copy()
        return b"%PDF"


def _fake_erp():
    mod = types.ModuleType("erp_contratistas")

    def fechas_consulta_contratistas_cc(conn, cc_u):
        return date(2026, 1, 1), date(2026, 11, 12)

    def listar_contratistas(conn, solo_activos=False):
        return [(3, "HERNAN ARAVENA", "1-9", "Activo")]

    def query_cuenta_corriente_contratista(conn, contratista_id, fi, ff, cc_u=None):
        return (
            pd.DataFrame(
                [{
                    "FECHA": date(2026, 11, 6),
                    "TIPO": "TRABAJO",
                    "DOCUMENTO": "CONTR-1",
                    "DETALLE": "cosecha SA",
                    "DEBE": 1000.0,
                    "HABER": 0.0,
                    "SALDO": 1000.0,
                }]
            ),
            "HERNAN ARAVENA",
        )

    mod.fechas_consulta_contratistas_cc = fechas_consulta_contratistas_cc
    mod.listar_contratistas = listar_contratistas
    mod.query_cuenta_corriente_contratista = query_cuenta_corriente_contratista
    return mod


class TestPdfCuenta(unittest.TestCase):
    def test_la_cuenta_arma_el_pdf_con_cc(self):
        app = Flask(__name__)
        app.secret_key = "test"
        demo = _Demo()
        conn = _conn()
        guardar_tipo_trabajo(conn, "CONTR-1", 3, "raleo")
        prev = sys.modules.get("erp_contratistas")
        sys.modules["erp_contratistas"] = _fake_erp()
        try:
            with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=True), patch(
                "demo_web.services.native.rrhh.url_for", return_value="/pdf"
            ):
                with app.test_request_context("/rrhh?sec=contratistas&sub=cuenta"):
                    ctx = _contratistas_cuenta(demo, conn)
        finally:
            if prev is None:
                sys.modules.pop("erp_contratistas", None)
            else:
                sys.modules["erp_contratistas"] = prev
        self.assertEqual(ctx["cta_rows"][0]["cc"], "SWEET ARYANA, ROYAL DOWN")
        self.assertEqual(ctx["cta_rows"][0]["tipo_trabajo"], "raleo")
        self.assertEqual(demo.pdf.iloc[0]["CC"], "SWEET ARYANA, ROYAL DOWN")
        self.assertEqual(demo.pdf.iloc[0]["TIPO DE TRABAJO"], "raleo")
        self.assertTrue(ctx["pdf_cta_url"])
