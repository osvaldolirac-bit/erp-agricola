"""El perfil lector consulta en pantalla y no descarga archivos."""
from __future__ import annotations

import unittest

from demo_web.app import lector_pide_descarga


class LectorDescargaTests(unittest.TestCase):
    def test_el_pdf_y_el_excel_cuentan_como_descarga(self):
        self.assertTrue(lector_pide_descarga("/agricola/m/pdf/abc", {}))
        self.assertTrue(lector_pide_descarga("/agricola/m/pdf/view/abc", {}))
        self.assertTrue(lector_pide_descarga("/agricola/m/fitosanitarios/cerezo/pdf", {}))
        self.assertTrue(lector_pide_descarga("/agricola/m/flujo/excel", {}))
        self.assertTrue(lector_pide_descarga("/agricola/m/globalgap", {"download_doc": "4"}))
        self.assertTrue(lector_pide_descarga("/agricola/m/petroleo", {}, "planilla_pdf"))

    def test_consultar_la_pantalla_no_es_descarga(self):
        self.assertFalse(lector_pide_descarga("/agricola/m/dashboard", {}))
        self.assertFalse(lector_pide_descarga("/agricola/m/compras", {}))
        self.assertFalse(lector_pide_descarga("/agricola/m/tesoreria", {}, "filtrar"))
        self.assertFalse(lector_pide_descarga("/agricola/static/css/erp.css", {}))


if __name__ == "__main__":
    unittest.main()
