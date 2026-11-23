"""Al editar una cotización la versión sube y el PDF lleva la V en el nombre."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "riomaipo_vps"))

from rmweb import core  # noqa: E402


class CotizacionVersionPdfTests(unittest.TestCase):
    def test_editar_sin_cambiar_el_numero_sube_la_version(self) -> None:
        self.assertEqual(
            core.version_al_guardar(
                "1", "1", editando=True, estado="enviada", estado_anterior="enviada"
            ),
            "2",
        )
        self.assertEqual(
            core.version_al_guardar(
                "V2", "2", editando=True, estado="enviada", estado_anterior="enviada"
            ),
            "3",
        )

    def test_editar_con_otro_numero_respeta_lo_escrito(self) -> None:
        self.assertEqual(
            core.version_al_guardar(
                "1", "V5", editando=True, estado="enviada", estado_anterior="enviada"
            ),
            "5",
        )

    def test_borrador_se_muestra_como_v_borrador_y_el_numero_nace_al_enviar(self) -> None:
        self.assertEqual(
            core.version_al_guardar(
                "borrador", "borrador", editando=True, estado="borrador", estado_anterior="borrador"
            ),
            "borrador",
        )
        self.assertEqual(
            core.version_al_guardar(
                "borrador", "borrador", editando=True, estado="enviada", estado_anterior="borrador"
            ),
            "1",
        )
        self.assertEqual(core.version_al_cambiar_estado("borrador", "enviada", "borrador"), "1")
        self.assertEqual(core.version_al_cambiar_estado("1", "aprobada", "enviada"), "1")
        self.assertEqual(core.etiqueta_v_cotizacion("1", "borrador"), "V borrador")
        self.assertEqual(core.etiqueta_v_cotizacion("2", "enviada"), "V2")

    def test_cotizacion_nueva_no_sube_sola(self) -> None:
        self.assertEqual(core.version_al_guardar("1", "1", editando=False, estado="enviada"), "1")
        self.assertEqual(core.version_al_guardar(None, "V3", editando=False, estado="enviada"), "3")
        self.assertEqual(core.version_al_guardar(None, "1", editando=False, estado="borrador"), "borrador")

    def test_el_pdf_lleva_la_v_y_el_folio(self) -> None:
        cot = {
            "estado": "enviada",
            "version": "2",
            "folio": "COT-0018",
            "titulo": "Muro",
            "razon_social": "Cliente Sur",
            "proyecto": "Obra norte",
            "asunto": "Radier",
        }
        self.assertEqual(
            core.cotizacion_nombre_pdf(cot),
            "V2 - COT-0018 - Cliente Sur - Obra norte - Radier.pdf",
        )
        self.assertEqual(core.cotizacion_etiqueta_version(cot), "V2 COT-0018")
        self.assertEqual(core.nombre_pantalla_cotizacion(cot), "V2 COT-0018")
        self.assertTrue(core.cotizacion_titulo_pdf(cot).startswith("V2 "))
        borrador = dict(cot, estado="borrador", version="borrador")
        self.assertEqual(core.nombre_pantalla_cotizacion(borrador), "V borrador COT-0018")
        self.assertTrue(core.cotizacion_nombre_pdf(borrador).startswith("V borrador - COT-0018"))

    def test_el_pdf_generado_muestra_la_v(self) -> None:
        cot = {
            "version": "4",
            "folio": "COT-0007",
            "titulo": "Radier",
            "razon_social": "Cliente",
            "estado": "enviada",
            "fecha": "2026-11-21",
            "gg_pct": 0,
            "utilidad_pct": 0,
            "gg_monto": 0,
            "utilidad_monto": 0,
            "iva": 0,
            "total": 1000,
        }
        items = [
            {
                "descripcion": "Hormigón",
                "obs": "",
                "unidad": "m3",
                "cantidad": 1,
                "precio_unitario": 1000,
                "total": 1000,
                "orden": 1,
            }
        ]
        pdf = core.cotizacion_pdf_bytes(cot, items, None, iva_pct=0.19)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"V4 COT-0007", pdf)


class CuentaPdfCotizacionTest(unittest.TestCase):
    def test_abono_pdf_trae_nombre_y_detalle_vigente(self):
        cot = {
            "folio": "COT-30_2026",
            "version": "2",
            "estado": "aprobada",
            "titulo": "SALVADOR GARCES BERNALES",
            "proyecto": "Fray Montalva",
            "asunto": "Elevaciones",
            "razon_social": "SALVADOR GARCES BERNALES",
            "subtotal": 1691985,
            "gg_pct": 5,
            "gg_monto": 84599,
            "utilidad_pct": 15,
            "utilidad_monto": 253798,
            "valor_neto": 2030382,
            "iva": 0,
            "total": 2030382,
        }
        items = [
            {"descripcion": "MADERA", "obs": "", "unidad": "M2", "cantidad": 30.5, "precio_unitario": 0, "total": 0},
            {"descripcion": "MADERA", "obs": "30,5 M2", "unidad": "un", "cantidad": 1, "precio_unitario": 0, "total": 0},
            {"descripcion": "materiales", "obs": "tornillos, lija desvaste, discos corte", "unidad": "un", "cantidad": 1, "precio_unitario": 40000, "total": 40000},
            {"descripcion": "protector cutex", "obs": "", "unidad": "GL", "cantidad": 1, "precio_unitario": 250000, "total": 250000},
        ]
        self.assertEqual(
            core.concepto_desde_cotizacion(cot),
            "Desde cotización V2 COT-30_2026 · Fray Montalva · Elevaciones",
        )
        cuenta = {
            "documento": "EP-0022",
            "concepto": "Desde cotización COT-30_2026 · SALVADOR GARCES BERNALES",
            "fecha_emision": "2026-11-22",
            "fecha_vencimiento": "2026-12-22",
            "monto": 2030382,
            "abonado": 700000,
            "saldo": 1330382,
            "estado": "parcial",
            "razon_social": "SALVADOR GARCES BERNALES",
            "cliente_rut": "14123582-6",
            "tipo": "EP",
        }
        abonos = [{"fecha": "2026-11-23", "monto": 700000, "medio": "Transferencia", "nota": ""}]
        pdf = core.cuenta_pdf_bytes(cuenta, abonos, None, cot=cot, items=items)
        self.assertTrue(pdf.startswith(b"%PDF"))
        from io import BytesIO
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("V2 COT-30_2026", text)
        self.assertIn("Fray Montalva", text)
        self.assertIn("Elevaciones", text)
        self.assertIn("Detalle de la cotizaci", text)
        self.assertIn("protector cutex", text)
        self.assertIn("30,5 M2", text)
        self.assertIn("tornillos, lija desvaste, discos corte", text)
        self.assertIn("Gastos generales", text)
