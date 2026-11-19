"""Presupuesto y producción aceptan montos que no son múltiplos redondos."""
from pathlib import Path
import unittest

from demo_web.services.native._helpers import format_monto_input_cl, parse_meta_imputacion

ROOT = Path(__file__).resolve().parents[1]


class PptoMetasTests(unittest.TestCase):
    def test_acepta_montos_que_no_son_de_cien_mil(self):
        self.assertEqual(parse_meta_imputacion("850000"), 850000.0)
        self.assertEqual(parse_meta_imputacion("1.250.500"), 1250500.0)
        self.assertEqual(parse_meta_imputacion("12,5"), 12.5)
        self.assertEqual(parse_meta_imputacion(""), 0.0)
        self.assertIsNone(parse_meta_imputacion("no"))
        self.assertEqual(format_monto_input_cl(1250500), "1.250.500")
        self.assertEqual(format_monto_input_cl(12.5), "12,5")

    def test_la_pantalla_no_obliga_el_paso_redondo(self):
        html = (ROOT / "demo_web/templates/modules/administracion.html").read_text(encoding="utf-8")
        ppto = html.split("sec_activa == 'ppto'", 1)[1].split("sec_activa == 'flujo'", 1)[0]
        self.assertNotIn('step="100000"', ppto)
        self.assertNotIn('step="100"', ppto)
        self.assertNotIn("|int", ppto)
        self.assertEqual(ppto.count("js-decimal-coma"), 2)
        self.assertIn("ppto_input", ppto)
        self.assertIn("kg_input", ppto)


if __name__ == "__main__":
    unittest.main()
