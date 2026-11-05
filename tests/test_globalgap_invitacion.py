"""Invitación GlobalGAP: prueba de 30 días y copia sin la clave."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "erp_master"))

from erp_master.globalgap_invitacion import (
    GLOBALGAP_LOGIN_URL,
    copias_sin_clave,
    cuerpo_invitacion_globalgap,
    enviar_invitacion_globalgap,
    fecha_fin_prueba,
)


class TestInvitacionGlobalgap(unittest.TestCase):
    def test_treinta_dias_desde_el_alta(self):
        self.assertEqual(fecha_fin_prueba(date(2026, 11, 5), 30), "2026-12-05")

    def test_la_copia_no_lleva_la_clave_ni_repite_al_invitado(self):
        copias = copias_sin_clave(
            "osvaldolirac@gmail.com",
            "rscertificaciones@gmail.com",
            ["osvaldolirac@gmail.com", "rscertificaciones@gmail.com", "otro@correo.cl"],
        )
        self.assertEqual(copias, ["osvaldolirac@gmail.com", "otro@correo.cl"])

    def test_el_cuerpo_del_invitado_trae_el_portal_y_la_clave(self):
        html = cuerpo_invitacion_globalgap(
            email="invitado@correo.cl",
            rol_txt="admin",
            fecha_expira="2026-12-05",
            admin_email="osvaldolirac@gmail.com",
            clave="clave-de-prueba",
        )
        self.assertIn(GLOBALGAP_LOGIN_URL, html)
        self.assertIn("clave-de-prueba", html)
        self.assertIn("05-12-2026", html)
        self.assertIn("consultor GlobalGAP", html)
        self.assertNotIn("Acceso permanente", html)

    def test_la_copia_no_repite_la_contrasena(self):
        html = cuerpo_invitacion_globalgap(
            email="invitado@correo.cl",
            rol_txt="admin",
            fecha_expira="2026-12-05",
            admin_email="osvaldolirac@gmail.com",
            clave="clave-de-prueba",
            para_copia=True,
        )
        self.assertNotIn("clave-de-prueba", html)
        self.assertIn("no incluye la contraseña", html)
        self.assertIn(GLOBALGAP_LOGIN_URL, html)

    def test_el_envio_avisa_al_invitado_y_copia_sin_clave(self):
        enviados = []

        def enviar(asunto, cuerpo, destinatarios):
            enviados.append((asunto, cuerpo, list(destinatarios)))
            return True

        ok, msg = enviar_invitacion_globalgap(
            email="invitado@correo.cl",
            password_plain="clave-de-prueba",
            rol="admin",
            admin_email="osvaldolirac@gmail.com",
            fecha_expira="2026-12-05",
            enviar_html=enviar,
        )
        self.assertTrue(ok)
        self.assertIn("osvaldolirac@gmail.com", msg)
        self.assertEqual(len(enviados), 2)
        self.assertIn("clave-de-prueba", enviados[0][1])
        self.assertNotIn("clave-de-prueba", enviados[1][1])
        self.assertEqual(enviados[1][2], ["osvaldolirac@gmail.com"])

    def test_sin_clave_igual_sale_la_copia(self):
        enviados = []

        def enviar(asunto, cuerpo, destinatarios):
            enviados.append((asunto, list(destinatarios), "clave-de-prueba" in cuerpo))
            return True

        ok, _msg = enviar_invitacion_globalgap(
            email="invitado@correo.cl",
            password_plain="",
            rol="admin",
            admin_email="osvaldolirac@gmail.com",
            fecha_expira="2026-12-05",
            enviar_html=enviar,
            incluir_clave_al_invitado=False,
        )
        self.assertTrue(ok)
        self.assertEqual([item[2] for item in enviados], [False, False])


class TestPortalCierraPrueba(unittest.TestCase):
    def test_fecha_vacia_sigue_y_la_vencida_no(self):
        from demo_web.blueprints.globalgap_portal import acceso_prueba_vigente

        self.assertTrue(acceso_prueba_vigente(None))
        self.assertTrue(acceso_prueba_vigente(""))
        self.assertTrue(acceso_prueba_vigente("2099-01-01"))
        self.assertFalse(acceso_prueba_vigente("2020-01-01"))


if __name__ == "__main__":
    unittest.main()
