"""Espino Libro ↔ bodega — guards de tenant y cuartel = variedad."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.espino_aplicacion_service import (
    EspinoAplicacionError,
    assert_tenant_espino,
    guardar_aplicacion_espino,
)
from demo_web.services.espino_bodega_desfase import excluir_desfase_ligado
from demo_web.services.espino_scope import cuartel_visible_libro


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


class TestCuartelVisible(unittest.TestCase):
    def test_variedad_gana_sobre_el_espino(self):
        self.assertEqual(cuartel_visible_libro("EL ESPINO", "Sweet Aryana"), "SWEET ARYANA")
        self.assertEqual(cuartel_visible_libro("EL ESPINO", "Royal Down"), "ROYAL DOWN")
        self.assertEqual(cuartel_visible_libro("SANTINA", "Santina"), "SANTINA")
        self.assertEqual(cuartel_visible_libro("CEREZOS", "Santina"), "CEREZOS")

    def test_desfase_ignora_salida_ya_ligada(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE inventario (id INTEGER PRIMARY KEY, producto TEXT);
            CREATE TABLE movimientos (
                id INTEGER PRIMARY KEY, fecha TEXT, centro_costo TEXT, producto_id INTEGER);
            CREATE TABLE libro_campo (
                id INTEGER PRIMARY KEY, n_aplicacion INTEGER, producto TEXT, movimiento_id INTEGER);
            INSERT INTO inventario VALUES (1, 'ESPINOSAD 480 SC');
            INSERT INTO movimientos VALUES (146, '2026-10-29', 'EL ESPINO', 1);
            INSERT INTO libro_campo VALUES (211, 21, 'ESPINOSAD 480 SC', 146);
            """
        )
        lc = [{"N° APP": 21, "PRODUCTO": "ESPINOSAD 480 SC", "CUARTEL": "ROYAL DOWN"}]
        bod = [{"FECHA": "2026-10-29", "PRODUCTO": "ESPINOSAD 480 SC", "CUARTEL": "EL ESPINO"}]
        otro = [{"FECHA": "2026-10-01", "PRODUCTO": "OTRO", "CUARTEL": "EL ESPINO"}]
        lc2, bod2 = excluir_desfase_ligado(conn, lc, bod + otro)
        self.assertEqual(lc2, [])
        self.assertEqual(bod2, otro)


class _Demo:
    DEFAULT_UNIDAD_INSUMO = "lt"
    last_huerto = ""

    def _insertar_linea_libro_campo(self, conn, fe, n_app, huerto, especie, item, *args, **kwargs):
        self.last_huerto = huerto
        conn.execute(
            """INSERT INTO libro_campo
               (fecha, n_aplicacion, sector, especie, producto, gasto_total, variedad)
               VALUES (?,?,?,?,?,?, '')""",
            (str(fe), n_app, huerto, especie, item["producto"], item["gasto_total"]),
        )


def _conn_bodega():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE inventario (
            id INTEGER PRIMARY KEY, producto TEXT, stock REAL, precio_medio REAL, unidad_medida TEXT);
        CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER, tipo TEXT, cantidad REAL, fecha TEXT,
            centro_costo TEXT, valor_imputado REAL, unidad_medida TEXT);
        CREATE TABLE libro_campo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, n_aplicacion INTEGER, sector TEXT, especie TEXT,
            producto TEXT, gasto_total REAL, variedad TEXT, movimiento_id INTEGER);
        INSERT INTO inventario VALUES (1, 'ESPINOSAD 480 SC', 10, 100, 'lt');
        INSERT INTO movimientos (producto_id, tipo, cantidad, fecha, centro_costo, valor_imputado, unidad_medida)
        VALUES (1, 'Ingreso', 10, '2026-10-01', 'EL ESPINO', 1000, 'lt');
        """
    )
    return conn


class TestGuardarCuartelVariedad(unittest.TestCase):
    def test_sector_es_la_variedad_y_bodega_sigue_en_el_espino(self):
        conn = _conn_bodega()
        demo = _Demo()
        res = guardar_aplicacion_espino(
            conn,
            demo,
            tenant_slug="espino",
            car=[{"producto": "ESPINOSAD 480 SC", "gasto_total": 1}],
            fe_app="2026-10-29",
            huerto="Sweet Aryana",
            especie="Cerezos",
            total_agua=100,
            aplicador="t",
            op_cert=False,
            maquinaria="NEB",
            tractor="",
            n_app_fn=lambda c: 22,
            n_orden_fn=lambda c: "1",
        )
        self.assertEqual(res.n_app, 22)
        sector, variedad = conn.execute(
            "SELECT sector, variedad FROM libro_campo WHERE n_aplicacion=22"
        ).fetchone()
        self.assertEqual(sector, "SWEET ARYANA")
        self.assertEqual(variedad, "Sweet Aryana")
        cc = conn.execute(
            "SELECT centro_costo FROM movimientos WHERE tipo='Salida'"
        ).fetchone()[0]
        self.assertEqual(cc, "EL ESPINO")

    def test_rechaza_cerezos_y_el_espino_como_cuartel(self):
        conn = _conn_bodega()
        demo = _Demo()
        for malo in ("Cerezos", "EL ESPINO", "CEREZOS"):
            with self.assertRaises(EspinoAplicacionError):
                guardar_aplicacion_espino(
                    conn,
                    demo,
                    tenant_slug="espino",
                    car=[{"producto": "ESPINOSAD 480 SC", "gasto_total": 1}],
                    fe_app="2026-10-29",
                    huerto=malo,
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
