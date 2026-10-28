"""Los correos de pago de Tesorería abren con el billete con alas."""
from __future__ import annotations

import unittest

from demo_web.services.native.tesoreria import asunto_pago_tesoreria, con_billete_pago


class TesoreriaMailPagoTests(unittest.TestCase):
    def test_el_respaldo_interno_lleva_el_billete(self):
        asunto = asunto_pago_tesoreria("La Concepción", "Proveedor SA", 2)
        self.assertTrue(asunto.startswith("💸"))
        self.assertNotIn("🚨", asunto)
        self.assertIn("Pago Procesado: Proveedor SA (2 doc.)", asunto)

    def test_el_correo_al_proveedor_lleva_el_billete(self):
        asunto, cuerpo = con_billete_pago(
            "[ERPMASTER] Pago registrado — Norte (1 doc.)",
            "<h2>Comprobante de pago registrado</h2>",
        )
        self.assertEqual(asunto, "💸 [ERPMASTER] Pago registrado — Norte (1 doc.)")
        self.assertIn("💸 Comprobante de pago registrado", cuerpo)

    def test_no_repite_el_billete(self):
        asunto, cuerpo = con_billete_pago(
            "💸 [ERP] Pago Procesado: A (1 doc.)",
            "<h2>💸 Egreso registrado en Tesorería</h2>",
        )
        self.assertEqual(asunto.count("💸"), 1)
        self.assertEqual(cuerpo.count("💸"), 1)


if __name__ == "__main__":
    unittest.main()
