"""Tests dominio LC — sin Flask; no toca DB de Espino."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.lc_aplicacion_service import (
    LcAplicacionError,
    assert_tenant_lc,
    guardar_aplicacion_lc,
)


class TestLcTenantGuard(unittest.TestCase):
    def test_solo_concepcion(self):
        assert_tenant_lc("concepcion")
        with self.assertRaises(LcAplicacionError):
            assert_tenant_lc("espino")
        with self.assertRaises(LcAplicacionError):
            assert_tenant_lc("")


class TestGuardarRollback(unittest.TestCase):
    def test_rechaza_espino(self):
        conn = sqlite3.connect(":memory:")
        class Demo:
            pass

        with self.assertRaises(LcAplicacionError):
            guardar_aplicacion_lc(
                conn,
                Demo(),
                tenant_slug="espino",
                car=[{"producto": "X", "gasto_total": 1}],
                fe_app="2026-01-01",
                huerto="CIRUELOS",
                especie="Ciruelos",
                total_agua=100,
                aplicador="test",
                op_cert=False,
                maquinaria="NEB-01",
                tractor="",
                n_app_fn=lambda c: 1,
                n_orden_fn=lambda c, s: "1",
                rebaje_bodega=False,
            )


if __name__ == "__main__":
    unittest.main()
