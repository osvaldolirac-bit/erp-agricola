#!/usr/bin/env python3
"""Tests modificar Libro de Campo — linea_id obsoleto al cambiar n_app."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class LibroCampoModificarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE libro_campo (
                id INTEGER PRIMARY KEY,
                n_aplicacion INTEGER,
                fecha TEXT,
                sector TEXT,
                especie TEXT,
                producto TEXT,
                lote_producto TEXT,
                ingrediente TEXT,
                dosis REAL,
                unidad_dosis TEXT,
                vol_total REAL,
                gasto_total REAL,
                aplicadores TEXT,
                maquina TEXT,
                tractor TEXT,
                fecha_viable TEXT
            );
            INSERT INTO libro_campo VALUES
              (10, 2, '2026-01-01', 'Cerezos', 'Cerezos', 'COBRE', '', 'cobre', 1, 'Litros (L)', 100, 2, 'Juan', 'NEB-01', '', '2026-01-15'),
              (20, 1, '2026-01-02', 'Cerezos', 'Cerezos', 'PIRIPROXIFEN', '', 'piri', 0.5, 'Litros (L)', 80, 1, 'Ana', 'NEB-01', '', '2026-01-20');
            CREATE TABLE maestra_maquinaria (
                id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT, tipo TEXT,
                activo INTEGER, orden INTEGER, notas TEXT
            );
            INSERT INTO maestra_maquinaria (codigo, nombre, tipo, activo, orden, notas)
            VALUES ('NEB-01', 'Nebulizador', 'Nebulizador', 1, 0, '');
            CREATE TABLE schema_meta (clave TEXT PRIMARY KEY, valor TEXT);
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_modificar_n1_con_linea_id_de_otra_app_no_crash(self) -> None:
        from demo_web.services.native import libro_campo as lc
        from flask import Flask

        app = Flask(__name__)
        demo = type("Demo", (), {"es_admin": lambda self: True})()

        import sys
        import types

        stub = types.ModuleType("erp_solo_lectura")
        stub.conn_en_solo_lectura = lambda conn: False
        erp_maq = types.ModuleType("erp_maquinaria")
        erp_maq.TIPOS_MAQUINARIA_APLICACION = ("Nebulizador",)
        erp_maq.TIPOS_MAQUINARIA_TRACTOR = ("Tractor",)

        with app.test_request_context("/?n_app=1&linea_id=10"):
            with patch.dict(sys.modules, {"erp_solo_lectura": stub, "erp_maquinaria": erp_maq}):
                with patch("demo_web.services.native.libro_campo.is_espino_tenant", return_value=True):
                    with patch("demo_web.services.native.libro_campo.centros_costo", return_value=["Cerezos"]):
                        with patch("demo_web.services.native.libro_campo._especies_libro_campo", return_value=["Cerezos"]):
                            with patch("demo_web.services.native.libro_campo._ensure_maquinaria_tenant"):
                                with patch(
                                    "demo_web.services.native.libro_campo._opciones_maquinaria",
                                    return_value=[("NEB-01", "NEB-01 — Nebulizador")],
                                ):
                                    ctx = lc._modificar(demo, self.conn)

        self.assertEqual(ctx["mod_app_sel"], 1)
        self.assertIsNotNone(ctx["mod_edit"])
        self.assertEqual(ctx["mod_edit"]["id"], 20)
        self.assertEqual(ctx["mod_edit"]["producto"], "PIRIPROXIFEN")

    def test_safe_n_aplicacion(self) -> None:
        from demo_web.services.native.libro_campo import _safe_n_aplicacion

        self.assertEqual(_safe_n_aplicacion("1"), 1)
        self.assertEqual(_safe_n_aplicacion(1.0), 1)
        self.assertIsNone(_safe_n_aplicacion(""))
        self.assertIsNone(_safe_n_aplicacion("abc"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
