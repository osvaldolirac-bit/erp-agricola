"""El abono de la cuenta corriente paga en Tesorería el documento más antiguo."""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from demo_web.services.contratista_cuenta import documentos_con_saldo, repartir_abono
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
            contratista_id INTEGER
        )"""
    )
    conn.execute("CREATE TABLE contratistas (id INTEGER PRIMARY KEY, razon_social TEXT)")
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
        self.assertIn("CONTR-07 queda con saldo", res["msg"])
