"""La clave de prueba demo no aparece en la copia de respaldo ni es elegida por la consola."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "erp_master" / "erp_master" / "tenant_admin.py"
_spec = importlib.util.spec_from_file_location("tenant_admin_demo_clave", _PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
generar_clave_demo = _mod.generar_clave_demo
_cuerpo_invitacion_demo = _mod._cuerpo_invitacion_demo


class DemoClaveSecretaTest(unittest.TestCase):
    def test_clave_aleatoria_no_es_trivial(self) -> None:
        a = generar_clave_demo()
        b = generar_clave_demo()
        self.assertGreaterEqual(len(a), 10)
        self.assertNotEqual(a, b)
        self.assertNotIn(" ", a)

    def test_copia_admin_no_incluye_la_clave(self) -> None:
        clave = "SecretaDemo99"
        invitado = _cuerpo_invitacion_demo(
            email="prueba@example.com",
            rol_txt="operador",
            fecha_txt="18-11-2026",
            login_url="https://erpmaster.cl/agricola/login",
            admin_email="admin@example.com",
            clave=clave,
        )
        copia = _cuerpo_invitacion_demo(
            email="prueba@example.com",
            rol_txt="operador",
            fecha_txt="18-11-2026",
            login_url="https://erpmaster.cl/agricola/login",
            admin_email="admin@example.com",
            clave="",
        )
        self.assertIn(clave, invitado)
        self.assertNotIn(clave, copia)
        self.assertIn("solo", copia.lower())


if __name__ == "__main__":
    unittest.main()
