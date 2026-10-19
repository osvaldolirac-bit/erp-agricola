"""Filtros LC vs datos El Espino."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from demo_web.services.lc_query_scope import (
    CUARTEL_ESPINO_LC,
    cuarteles_costos_lc,
    cuarteles_matriz_costos_lc,
    es_razon_social_espino_excluida,
    filtrar_df_facturas_espino_lc,
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


if __name__ == "__main__":
    unittest.main()
