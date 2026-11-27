"""La cuenta corriente de RRHH se abre con el nombre del PDF, no con la URL del token."""
from __future__ import annotations

import unittest

from demo_web.services.native.rrhh import nombre_pdf_cuenta_corriente
from demo_web.services.pdf_meta import stamp_pdf_title


class NombrePdfCuentaTest(unittest.TestCase):
    def test_nombre_del_contratista(self):
        self.assertEqual(
            nombre_pdf_cuenta_corriente("Alejandra Levimán"),
            "Cuenta_corriente_Alejandra_Leviman.pdf",
        )

    def test_agrega_el_centro_de_costo(self):
        self.assertEqual(
            nombre_pdf_cuenta_corriente("Juan Pérez", "Cerezos corte 1"),
            "Cuenta_corriente_Juan_Perez_Cerezos_corte_1.pdf",
        )

    def test_sin_nombre_usa_contratista(self):
        self.assertEqual(nombre_pdf_cuenta_corriente(""), "Cuenta_corriente_contratista.pdf")


class TituloPdfTest(unittest.TestCase):
    def test_fpdf2_sin_producer_recibe_el_nombre(self):
        blob = b"%PDF-1.3\n7 0 obj\n<<\n/CreationDate (D:20261127)\n>>\nendobj\n"
        out = stamp_pdf_title(blob, "Cuenta_corriente_Alejandra_Leviman.pdf")
        self.assertIn(b"/Title (Cuenta corriente Alejandra Leviman)", out)
        self.assertIn(b"/CreationDate", out)
        self.assertNotIn(b"http", out)

    def test_no_pisa_un_titulo_existente(self):
        blob = b"%PDF-1.3\n<< /Title (Ya tiene) /CreationDate (D:20261127) >>\n"
        self.assertEqual(stamp_pdf_title(blob, "Otro.pdf"), blob)

    def test_producer_antiguo_sigue_recibiendo_el_titulo(self):
        blob = b"%PDF-1.3\n<< /Producer (FPDF) >>\n"
        out = stamp_pdf_title(blob, "Cuenta_corriente_Juan.pdf")
        self.assertIn(b"/Title (Cuenta corriente Juan)", out)
        self.assertIn(b"/Producer (FPDF)", out)


if __name__ == "__main__":
    unittest.main()
