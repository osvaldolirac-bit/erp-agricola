"""Elegir empresa debe avisar el acceso. El ingreso de un solo tenant ya lo hacía."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from demo_web.auth import routes as auth_routes


class TestAlertaAlElegirEmpresa(unittest.TestCase):
    def test_avisa_cuando_hay_mas_de_una_empresa(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(auth_routes.bp)
        email = "secretarialaconcepcion2@gmail.com"
        with patch.object(auth_routes, "get_tenant", return_value={"slug": "espino", "nombre": "El Espino"}):
            with patch.object(auth_routes, "_activate_session") as activar:
                with patch.object(auth_routes, "_maybe_alert_login") as alerta:
                    with patch.object(auth_routes, "safe_next", return_value="/agricola/"):
                        with patch.object(auth_routes, "pop_login_next", return_value=None):
                            with app.test_client() as client:
                                with client.session_transaction() as sess:
                                    sess["pending_login"] = {
                                        "email": email,
                                        "options": [
                                            {"slug": "concepcion", "nombre": "La Concepción", "rol": "operador"},
                                            {"slug": "espino", "nombre": "El Espino", "rol": "operador"},
                                        ],
                                    }
                                resp = client.post("/login/empresa", data={"tenant_slug": "espino"})
        self.assertEqual(resp.status_code, 302)
        alerta.assert_called_once_with(email=email, exitoso=True, tenant_slug="espino")
        activar.assert_called_once()
