"""Consultas de contratistas en El Espino: las 3 variedades, no Cerezos."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd
from flask import Flask

from demo_web.services.espino_scope import VARIEDADES_ESPINO
from demo_web.services.native.espino_bodega import ETIQUETA_BODEGA
from demo_web.services.native.rrhh import _contratistas_cuenta, _contratistas_por_cc
from demo_web.services.tenant_scope import ESPINO_CCS

LC_CC = ["CEREZOS CORTE 1", "CEREZOS CORTE 2", "CIRUELOS", "NOGALES"]


class _Demo:
    def __init__(self, cuarteles):
        self.CUARTELES_OFICIALES = list(cuarteles)

    def f_peso(self, n):
        return f"{n}"

    def hora_chile(self):
        return datetime(2026, 10, 21, 12, 0, 0)


def _fake_erp(consultas: dict):
    mod = types.ModuleType("erp_contratistas")

    def fechas_consulta_contratistas_cc(conn, cc_u):
        consultas.setdefault("fechas", []).append(cc_u)
        return date(2026, 1, 1), date(2026, 10, 21)

    def listar_contratistas(conn, solo_activos=False):
        return [(1, "Alejandra Levimán", "1-9", "Activo")]

    def query_imputaciones_contratistas_cc(conn, cc, fi, ff, contratista_id=None):
        consultas.setdefault("por_cc", []).append(cc)
        return pd.DataFrame(columns=["MONTO", "FECHA", "CONTRATISTA", "DOCUMENTO", "SERVICIO"])

    def query_cuenta_corriente_contratista(conn, contratista_id, fi, ff, cc_u=None):
        consultas.setdefault("cuenta", []).append(cc_u)
        return (
            pd.DataFrame(columns=["DEBE", "HABER", "SALDO", "FECHA", "TIPO", "DOCUMENTO", "DETALLE"]),
            "Alejandra",
        )

    mod.fechas_consulta_contratistas_cc = fechas_consulta_contratistas_cc
    mod.listar_contratistas = listar_contratistas
    mod.query_imputaciones_contratistas_cc = query_imputaciones_contratistas_cc
    mod.query_cuenta_corriente_contratista = query_cuenta_corriente_contratista
    return mod


class TestContratistaVariedadesEspino(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.consultas: dict = {}
        self._prev = sys.modules.get("erp_contratistas")
        sys.modules["erp_contratistas"] = _fake_erp(self.consultas)

    def tearDown(self):
        if self._prev is None:
            sys.modules.pop("erp_contratistas", None)
        else:
            sys.modules["erp_contratistas"] = self._prev

    def test_espino_ignora_cerezos_y_lista_variedades(self):
        demo = _Demo(["Cerezos"])
        variedades = list(VARIEDADES_ESPINO)
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=True):
            with self.app.test_request_context("/rrhh?sec=contratistas&sub=por_cc&cc=Cerezos"):
                por = _contratistas_por_cc(demo, None)
            with self.app.test_request_context("/rrhh?sec=contratistas&sub=cuenta&cc_filtro=Cerezos"):
                cta = _contratistas_cuenta(demo, None)
            with self.app.test_request_context("/rrhh?sec=contratistas&sub=por_cc&cc=SANTINA"):
                santina = _contratistas_por_cc(demo, None)
            with self.app.test_request_context(
                "/rrhh?sec=contratistas&sub=cuenta&cc_filtro=SWEET%20ARYANA"
            ):
                aryana = _contratistas_cuenta(demo, None)

        self.assertEqual(por["cuarteles"], variedades)
        self.assertNotIn("Cerezos", por["cuarteles"])
        self.assertEqual(por["cc_sel"], "ROYAL DOWN")
        self.assertEqual(self.consultas["por_cc"][0], "ROYAL DOWN")
        self.assertEqual(cta["cc_filtro_opts"], variedades)
        self.assertEqual(cta["cc_filtro_sel"], "")
        self.assertIsNone(self.consultas["cuenta"][0])
        self.assertEqual(santina["cc_sel"], "SANTINA")
        self.assertEqual(self.consultas["por_cc"][1], "SANTINA")
        self.assertEqual(aryana["cc_filtro_sel"], "SWEET ARYANA")
        self.assertEqual(self.consultas["cuenta"][1], "SWEET ARYANA")

    def test_lc_conserva_sus_cuarteles(self):
        demo = _Demo(LC_CC)
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=False):
            with self.app.test_request_context("/rrhh?sec=contratistas&sub=por_cc&cc=CIRUELOS"):
                por = _contratistas_por_cc(demo, None)
            with self.app.test_request_context("/rrhh?sec=contratistas&sub=cuenta&cc_filtro=NOGALES"):
                cta = _contratistas_cuenta(demo, None)
        self.assertEqual(por["cuarteles"], LC_CC)
        self.assertEqual(por["cc_sel"], "CIRUELOS")
        self.assertEqual(self.consultas["por_cc"][-1], "CIRUELOS")
        self.assertEqual(cta["cc_filtro_opts"], LC_CC)
        self.assertEqual(cta["cc_filtro_sel"], "NOGALES")
        self.assertEqual(self.consultas["cuenta"][-1], "NOGALES")


def _clasificar_como_vps(seleccionados, directa, prorrateo):
    """Misma regla que app_concepcion._clasificar_cc_seleccionados."""
    sel = [str(c).strip().upper() for c in seleccionados if c]
    try:
        from demo_web.services.native.espino_bodega import ETIQUETA_BODEGA as etiqueta
        from demo_web.services.tenant_scope import ESPINO_CCS as ccs
        from demo_web.services.tenant_scope import is_espino_tenant

        if not etiqueta:
            raise RuntimeError("etiqueta vacía")
        if is_espino_tenant():
            valid = {c.upper() for c in ccs}
            directos = [c for c in sel if c in valid]
            invalid = [c for c in sel if c not in valid]
            return directos, [], invalid
    except Exception:
        pass
    directos = [c for c in sel if c in directa]
    prorr = [c for c in sel if c in prorrateo]
    invalid = [c for c in sel if c not in directos and c not in prorr]
    return directos, prorr, invalid


class TestClasificacionCcContratistaEspino(unittest.TestCase):
    def test_simbolos_que_importa_el_clasificador(self):
        self.assertEqual(ETIQUETA_BODEGA, "EL ESPINO")
        self.assertEqual(tuple(ESPINO_CCS), VARIEDADES_ESPINO)
        self.assertNotIn("CEREZOS", {c.upper() for c in ESPINO_CCS})

    def test_variedad_marcada_queda_solo_en_imputacion_directa(self):
        variedades = [c.upper() for c in VARIEDADES_ESPINO]
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=True):
            uno = _clasificar_como_vps(["SANTINA"], variedades, variedades)
            tres = _clasificar_como_vps(variedades, variedades, variedades)
            legado = _clasificar_como_vps(["Cerezos"], variedades, variedades)
        self.assertEqual(uno, (["SANTINA"], [], []))
        self.assertEqual(tres[0], variedades)
        self.assertEqual(tres[1], [])
        self.assertEqual(tres[2], [])
        self.assertEqual(legado, ([], [], ["CEREZOS"]))

    def test_sin_ramo_espino_la_variedad_cae_en_directo_y_prorrateo(self):
        variedades = [c.upper() for c in VARIEDADES_ESPINO]
        with patch("demo_web.services.tenant_scope.is_espino_tenant", return_value=False):
            directos, prorr, invalid = _clasificar_como_vps(["SANTINA"], variedades, variedades)
        self.assertEqual(directos, ["SANTINA"])
        self.assertEqual(prorr, ["SANTINA"])
        self.assertEqual(invalid, [])
        self.assertTrue(directos and prorr)


if __name__ == "__main__":
    unittest.main()
