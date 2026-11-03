"""LC: imputar un gasto por el bruto no lo convierte a neto en Costos."""
from __future__ import annotations

import sqlite3
import unittest

from demo_web.services.lc_imputacion_bruto import (
    instalar_imputacion_bruta_lc,
    marcar_imputacion_respeta_bruto,
)


class _Erp:
    def _factores_monto_bruto_facturas(self, conn, fi=None, ff=None):
        return {("INT-20261021-01_P", "COMERCIAL ROSA BASTIAS L"): 1.0}

    def _monto_costos_factura_imputada(self, factores, nro_p, prov, monto_imputado):
        return float(monto_imputado or 0) * factores.get((str(nro_p), str(prov)), 1.0)

    def _monto_costos_factura_matriz(self, rubro, monto, neto_facturas_iva=True):
        if neto_facturas_iva and rubro == "Repuestos y talleres":
            return float(monto or 0) / 1.19
        return float(monto or 0)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE facturas (
            id INTEGER PRIMARY KEY,
            nro_documento TEXT,
            proveedor TEXT,
            monto_total REAL,
            monto_imputado REAL,
            centro_costo TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO facturas (nro_documento, proveedor, monto_total, monto_imputado) "
        "VALUES ('INT-20261021-01', 'COMERCIAL ROSA BASTIAS L', 390000, 0)"
    )
    conn.execute(
        "INSERT INTO facturas (nro_documento, proveedor, monto_total, monto_imputado, centro_costo) "
        "VALUES ('INT-20261021-01_P', 'COMERCIAL ROSA BASTIAS L', 0, 390000, 'CIRUELOS')"
    )
    return conn


class TestImputacionBrutaLc(unittest.TestCase):
    def test_bruto_marcado_no_se_divide_en_ciruelos(self):
        erp = _Erp()
        instalar_imputacion_bruta_lc(erp)
        conn = _db()
        marcar_imputacion_respeta_bruto(conn, "INT-20261021-01", "COMERCIAL ROSA BASTIAS L", True)
        factores = erp._factores_monto_bruto_facturas(conn)
        scaled = erp._monto_costos_factura_imputada(
            factores, "INT-20261021-01_P", "COMERCIAL ROSA BASTIAS L", 390000,
        )
        costo = erp._monto_costos_factura_matriz("Repuestos y talleres", scaled)
        self.assertAlmostEqual(costo, 390000.0)

    def test_sin_marca_el_rubro_sigue_en_neto(self):
        erp = _Erp()
        instalar_imputacion_bruta_lc(erp)
        conn = _db()
        marcar_imputacion_respeta_bruto(conn, "INT-20261021-01", "COMERCIAL ROSA BASTIAS L", False)
        factores = erp._factores_monto_bruto_facturas(conn)
        scaled = erp._monto_costos_factura_imputada(
            factores, "INT-20261021-01_P", "COMERCIAL ROSA BASTIAS L", 390000,
        )
        costo = erp._monto_costos_factura_matriz("Repuestos y talleres", scaled)
        self.assertAlmostEqual(costo, 390000.0 / 1.19)

    def test_otra_linea_no_hereda_la_marca(self):
        erp = _Erp()
        instalar_imputacion_bruta_lc(erp)
        conn = _db()
        marcar_imputacion_respeta_bruto(conn, "INT-20261021-01", "COMERCIAL ROSA BASTIAS L", True)
        factores = erp._factores_monto_bruto_facturas(conn)
        erp._monto_costos_factura_imputada(
            factores, "INT-20261021-01_P", "COMERCIAL ROSA BASTIAS L", 390000,
        )
        # Una fila distinta, sin pasar por la imputación marcada, sigue a neto.
        costo = erp._monto_costos_factura_matriz("Repuestos y talleres", 119000.0)
        self.assertAlmostEqual(costo, 119000.0 / 1.19)


if __name__ == "__main__":
    unittest.main()
