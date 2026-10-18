"""Espino Libro ↔ bodega — guards de tenant."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.espino_aplicacion_service import (
    EspinoAplicacionError,
    assert_tenant_espino,
    guardar_aplicacion_espino,
)


class TestEspinoTenantGuard(unittest.TestCase):
    def test_solo_espino(self):
        assert_tenant_espino("espino")
        with self.assertRaises(EspinoAplicacionError):
            assert_tenant_espino("concepcion")

    def test_rechaza_concepcion_en_guardar(self):
        conn = sqlite3.connect(":memory:")
        class Demo:
            pass

        with self.assertRaises(EspinoAplicacionError):
            guardar_aplicacion_espino(
                conn,
                Demo(),
                tenant_slug="concepcion",
                car=[{"producto": "X", "gasto_total": 1}],
                fe_app="2026-01-01",
                especie="Cerezos",
                total_agua=100,
                aplicador="t",
                op_cert=False,
                maquinaria="NEB",
                tractor="",
                n_app_fn=lambda c: 1,
                n_orden_fn=lambda c: "1",
            )


if __name__ == "__main__":
    unittest.main()
