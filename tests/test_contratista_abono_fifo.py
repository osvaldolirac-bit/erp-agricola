"""El abono de la cuenta corriente paga en Tesorería el documento más antiguo."""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

import pandas as pd

from demo_web.services.contratista_cuenta import (
    documentos_con_saldo,
    presentar_cuenta,
    repartir_abono,
    unificar_abonos_libro,
)
from demo_web.services.native.rrhh import _post_abono_cuenta


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nro_documento TEXT,
            proveedor TEXT,
            fecha_compra TEXT,
            monto_total REAL,
            monto_pagado REAL DEFAULT 0,
            estado TEXT DEFAULT 'Pendiente',
            tipo_gasto TEXT,
            contratista_id INTEGER,
            centro_costo TEXT
        )"""
    )
    conn.execute("CREATE TABLE contratistas (id INTEGER PRIMARY KEY, razon_social TEXT)")
    conn.execute(
        """CREATE TABLE facturas_abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factura_id INTEGER,
            fecha TEXT,
            monto REAL,
            metodo_pago TEXT,
            usuario TEXT,
            fecha_registro TEXT,
            banco TEXT
        )"""
    )
    conn.execute("INSERT INTO contratistas VALUES (3, 'HERNAN ARAVENA')")
    conn.executemany(
        """INSERT INTO facturas
           (nro_documento, proveedor, fecha_compra, monto_total, monto_pagado, estado, tipo_gasto, contratista_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            ("CONTR-07", "HERNAN ARAVENA", "2026-11-07", 974000, 0, "Pendiente", "Contratistas", 3),
            ("CONTR-06", "HERNAN ARAVENA", "2026-11-06", 705400, 0, "Pendiente", "Contratistas", 3),
            ("CONTR-06_P", "HERNAN ARAVENA", "2026-11-06", 0, 0, "Pendiente", "Contratistas", 3),
            ("CONTR-05", "HERNAN ARAVENA", "2026-11-05", 100000, 100000, "Pagado", "Contratistas", 3),
            ("FAC-9", "OTRO", "2026-11-01", 50000, 0, "Pendiente", "Contratistas", 9),
        ],
    )
    return conn


class TestReparto(unittest.TestCase):
    def test_paga_el_mas_antiguo_y_deja_saldo_en_el_siguiente(self):
        docs = documentos_con_saldo(_conn(), 3, "HERNAN ARAVENA")
        self.assertEqual([d["nro"] for d in docs], ["CONTR-06", "CONTR-07"])
        partes, err = repartir_abono(docs, 800000)
        self.assertEqual(err, "")
        self.assertEqual(partes[0]["nro"], "CONTR-06")
        self.assertEqual(partes[0]["aplicar"], 705400)
        self.assertEqual(partes[0]["saldo_despues"], 0)
        self.assertEqual(partes[1]["nro"], "CONTR-07")
        self.assertEqual(partes[1]["aplicar"], 94600)
        self.assertEqual(partes[1]["saldo_despues"], 879400)

    def test_un_abono_parcial_no_toca_el_siguiente(self):
        docs = documentos_con_saldo(_conn(), 3, "HERNAN ARAVENA")
        partes, err = repartir_abono(docs, 50000)
        self.assertEqual(err, "")
        self.assertEqual(len(partes), 1)
        self.assertEqual(partes[0]["nro"], "CONTR-06")
        self.assertEqual(partes[0]["saldo_despues"], 655400)

    def test_no_acepta_mas_que_la_deuda(self):
        docs = documentos_con_saldo(_conn(), 3, "HERNAN ARAVENA")
        partes, err = repartir_abono(docs, 99999999)
        self.assertEqual(partes, [])
        self.assertIn("supera", err)


class _Demo:
    def __init__(self):
        self.acciones = []

    def hora_chile(self):
        from datetime import datetime
        return datetime(2026, 11, 13, 12, 0, 0)

    def f_peso(self, n):
        return f"${int(round(n))}"

    def registrar_accion(self, accion, detalle):
        self.acciones.append((accion, detalle))

    def _registrar_abono_factura(self, conn, doc_id, fecha, monto, metodo, usuario, banco=""):
        row = conn.execute(
            "SELECT nro_documento, monto_total, COALESCE(monto_pagado,0) FROM facturas WHERE id=?",
            (int(doc_id),),
        ).fetchone()
        pagado = float(row[2]) + float(monto)
        estado = "Pagado" if pagado >= float(row[1]) - 0.01 else "Pendiente"
        conn.execute(
            "UPDATE facturas SET monto_pagado=?, estado=? WHERE id=?",
            (pagado, estado, int(doc_id)),
        )
        conn.execute(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, usuario, banco)
               VALUES (?,?,?,?,?,?)""",
            (int(doc_id), str(fecha)[:10], float(monto), metodo, usuario, banco),
        )
        return True, {
            "nro_documento": row[0],
            "monto": monto,
            "estado": estado,
            "saldo_restante": float(row[1]) - pagado,
        }


class TestAbonoCuenta(unittest.TestCase):
    def test_el_abono_de_la_cuenta_paga_en_tesoreria(self):
        app = Flask(__name__)
        conn = _conn()
        demo = _Demo()
        data = {
            "contratista_id": "3",
            "monto": "800.000",
            "metodo_pago": "Transferencia",
            "banco": "BCI",
            "fecha_pago": "2026-11-13",
        }
        avisos = {}

        def _aviso(*args, **kwargs):
            avisos["args"] = args
            avisos["kwargs"] = kwargs
            return True, " Correo al contratista enviado."

        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=False), patch(
            "demo_web.services.native.tesoreria._avisos_pago", side_effect=_aviso
        ):
            with app.test_request_context("/", method="POST", data=data):
                res = _post_abono_cuenta(demo, conn, "osvaldo@laconcepcion.cl")
        self.assertTrue(res["ok"], res["msg"])
        self.assertTrue(avisos["args"][7] is True)
        self.assertEqual(
            [linea["nro_documento"] for linea in avisos["args"][3]],
            ["CONTR-06", "CONTR-07"],
        )
        self.assertIn("Correo de respaldo enviado al equipo", res["msg"])
        seis = conn.execute(
            "SELECT estado, monto_pagado FROM facturas WHERE nro_documento='CONTR-06'"
        ).fetchone()
        siete = conn.execute(
            "SELECT estado, monto_pagado FROM facturas WHERE nro_documento='CONTR-07'"
        ).fetchone()
        self.assertEqual(seis[0], "Pagado")
        self.assertEqual(seis[1], 705400)
        self.assertEqual(siete[0], "Pendiente")
        self.assertEqual(siete[1], 94600)
        self.assertIn("un solo monto", res["msg"])
        self.assertNotIn("CONTR-06", res["msg"])
        abonos = conn.execute(
            "SELECT factura_id, monto, abono_lote FROM facturas_abonos ORDER BY id"
        ).fetchall()
        self.assertEqual([a[1] for a in abonos], [705400, 94600])
        self.assertTrue(abonos[0][2])
        self.assertEqual(abonos[0][2], abonos[1][2])
        ids = {
            nro: fid
            for fid, nro in conn.execute("SELECT id, nro_documento FROM facturas")
        }
        libro = pd.DataFrame(
            [
                {"FECHA": "2026-11-06", "TIPO": "TRABAJO", "DOCUMENTO": "CONTR-06", "DETALLE": "faena", "DEBE": 705400.0, "HABER": 0.0, "SALDO": 705400.0},
                {"FECHA": "2026-11-07", "TIPO": "TRABAJO", "DOCUMENTO": "CONTR-07", "DETALLE": "faena", "DEBE": 974000.0, "HABER": 0.0, "SALDO": 1679400.0},
                {"FECHA": "2026-11-13", "TIPO": "PAGO", "DOCUMENTO": "CONTR-06", "DETALLE": "Pago (Transferencia)", "DEBE": 0.0, "HABER": 705400.0, "SALDO": 974000.0},
                {"FECHA": "2026-11-13", "TIPO": "PAGO", "DOCUMENTO": "CONTR-07", "DETALLE": "Pago (Transferencia)", "DEBE": 0.0, "HABER": 94600.0, "SALDO": 879400.0},
            ]
        )
        unido = unificar_abonos_libro(conn, libro)
        pagos = unido[unido["TIPO"] == "PAGO"]
        self.assertEqual(len(pagos), 1)
        self.assertEqual(float(pagos.iloc[0]["HABER"]), 800000.0)
        self.assertEqual(str(pagos.iloc[0]["DOCUMENTO"]), "")
        self.assertNotIn("CONTR-", str(pagos.iloc[0]["DETALLE"]))
        self.assertEqual(float(unido.iloc[-1]["SALDO"]), 879400.0)
        filas, _pdf = presentar_cuenta(conn, unido, demo.f_peso)
        self.assertEqual(filas[-1]["haber"], "$800000")
        self.assertEqual(filas[-1]["documento"], "")
        self.assertEqual(filas[-1]["cc"], "")
        self.assertEqual(ids["CONTR-06"], abonos[0][0])
        self.assertEqual(ids["CONTR-07"], abonos[1][0])

    def test_un_pago_de_tesoreria_sigue_en_su_documento(self):
        conn = _conn()
        seis = conn.execute("SELECT id FROM facturas WHERE nro_documento='CONTR-06'").fetchone()[0]
        conn.execute("ALTER TABLE facturas_abonos ADD COLUMN abono_lote TEXT DEFAULT ''")
        conn.execute(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, abono_lote)
               VALUES (?,?,?,?,?)""",
            (seis, "2026-11-13", 50000, "Transferencia", ""),
        )
        libro = pd.DataFrame(
            [
                {"FECHA": "2026-11-06", "TIPO": "TRABAJO", "DOCUMENTO": "CONTR-06", "DETALLE": "faena", "DEBE": 705400.0, "HABER": 0.0, "SALDO": 705400.0},
                {"FECHA": "2026-11-13", "TIPO": "PAGO", "DOCUMENTO": "CONTR-06", "DETALLE": "Pago (Transferencia)", "DEBE": 0.0, "HABER": 50000.0, "SALDO": 655400.0},
            ]
        )
        unido = unificar_abonos_libro(conn, libro)
        self.assertEqual(len(unido), 2)
        self.assertEqual(unido.iloc[1]["DOCUMENTO"], "CONTR-06")
        self.assertEqual(float(unido.iloc[1]["HABER"]), 50000.0)

    def test_el_abono_de_un_millon_es_una_linea(self):
        conn = _conn()
        ids = {
            nro: fid
            for nro, fid in conn.execute(
                "SELECT nro_documento, id FROM facturas WHERE nro_documento IN ('CONTR-06', 'CONTR-07')"
            )
        }
        conn.executemany(
            """INSERT INTO facturas_abonos (factura_id, fecha, monto, metodo_pago, fecha_registro)
               VALUES (?,?,?,?,?)""",
            [
                (ids["CONTR-06"], "2026-11-12", 745800, "Transferencia", "2026-11-13 09:30:10"),
                (ids["CONTR-07"], "2026-11-12", 254200, "Transferencia", "2026-11-13 09:30:10"),
            ],
        )
        libro = pd.DataFrame(
            [
                {"FECHA": "2026-11-12", "TIPO": "PAGO", "DOCUMENTO": "CONTR-06", "DETALLE": "Pago (Transferencia)", "DEBE": 0.0, "HABER": 745800.0, "SALDO": 0.0},
                {"FECHA": "2026-11-12", "TIPO": "PAGO", "DOCUMENTO": "CONTR-07", "DETALLE": "Pago (Transferencia)", "DEBE": 0.0, "HABER": 254200.0, "SALDO": -1000000.0},
            ]
        )
        unido = unificar_abonos_libro(conn, libro)
        pagos = unido[unido["TIPO"] == "PAGO"]
        self.assertEqual(len(pagos), 1)
        self.assertEqual(float(pagos.iloc[0]["HABER"]), 1000000.0)
        self.assertEqual(str(pagos.iloc[0]["DOCUMENTO"]), "")
        self.assertNotIn("CONTR-", str(pagos.iloc[0]["DETALLE"]))
        detalle = conn.execute(
            "SELECT f.nro_documento, fa.monto FROM facturas_abonos fa JOIN facturas f ON f.id=fa.factura_id ORDER BY fa.id"
        ).fetchall()
        self.assertEqual(detalle, [("CONTR-06", 745800), ("CONTR-07", 254200)])
