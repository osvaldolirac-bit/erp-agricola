"""Filtros LC vs datos El Espino."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from demo_web.services.lc_query_scope import (
    CUARTEL_ESPINO_LC,
    RUBRO_PETROLEO_COSTOS,
    cuarteles_costos_lc,
    cuarteles_matriz_costos_lc,
    es_razon_social_espino_excluida,
    filtrar_detalle_cc_solo_petroleo_lc,
    filtrar_df_facturas_espino_lc,
    matriz_costos_cc_espino_solo_petroleo_lc,
    sql_and_excluir_razon_social_espino,
)
from demo_web.services.tenant_scope import RAZON_SOCIAL_ESPINO


class TestLcQueryScope(unittest.TestCase):
    def test_es_razon_espino(self):
        self.assertTrue(es_razon_social_espino_excluida(RAZON_SOCIAL_ESPINO))
        self.assertFalse(es_razon_social_espino_excluida("La Concepción"))

    def test_sql_fragment_vacio_sin_request(self):
        self.assertEqual(sql_and_excluir_razon_social_espino(), "")

    def test_filtrar_df_sin_request_no_op(self):
        df = pd.DataFrame([{"razon_social": RAZON_SOCIAL_ESPINO}])
        out = filtrar_df_facturas_espino_lc(df)
        self.assertEqual(len(out), 1)

    @patch("demo_web.services.lc_query_scope._lc_excluir", return_value=True)
    def test_matriz_costos_mantiene_el_espino(self, _mock):
        base = ["CIRUELOS", CUARTEL_ESPINO_LC, "OTROS"]
        self.assertNotIn(CUARTEL_ESPINO_LC, cuarteles_costos_lc(base))
        self.assertIn(CUARTEL_ESPINO_LC, cuarteles_matriz_costos_lc(base))

    @patch("demo_web.services.lc_query_scope._lc_excluir", return_value=True)
    @patch("demo_web.services.lc_query_scope._sum_petroleo_salidas_cc", return_value=500.0)
    def test_matriz_espino_solo_petroleo(self, _sum, _mock):
        import sqlite3

        matriz = pd.DataFrame(
            [
                {"Rubro": "Insumos", CUARTEL_ESPINO_LC: 100.0, "CIRUELOS": 10.0, "TOTAL": 110.0},
                {"Rubro": RUBRO_PETROLEO_COSTOS, CUARTEL_ESPINO_LC: 50.0, "CIRUELOS": 5.0, "TOTAL": 55.0},
                {"Rubro": "PRESUPUESTO", CUARTEL_ESPINO_LC: 1000.0, "CIRUELOS": 100.0, "TOTAL": 1100.0},
            ]
        )
        conn = sqlite3.connect(":memory:")
        out = matriz_costos_cc_espino_solo_petroleo_lc(conn, matriz)
        ins = out[out["Rubro"] == "Insumos"].iloc[0]
        pet = out[out["Rubro"] == RUBRO_PETROLEO_COSTOS].iloc[0]
        self.assertEqual(float(ins[CUARTEL_ESPINO_LC]), 0.0)
        self.assertEqual(float(pet[CUARTEL_ESPINO_LC]), 500.0)

    @patch("demo_web.services.lc_query_scope._lc_excluir", return_value=True)
    def test_detalle_espino_solo_petroleo(self, _mock):
        df = pd.DataFrame(
            [
                {"Rubro": "Insumos", "Monto": 1},
                {"Rubro": RUBRO_PETROLEO_COSTOS, "Monto": 2},
            ]
        )
        out = filtrar_detalle_cc_solo_petroleo_lc(df, CUARTEL_ESPINO_LC)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["Rubro"], RUBRO_PETROLEO_COSTOS)


if __name__ == "__main__":
    unittest.main()
