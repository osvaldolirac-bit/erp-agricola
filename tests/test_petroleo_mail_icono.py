"""Los correos de salida y autorización de petróleo abren con el surtidor."""
from __future__ import annotations

import inspect
import unittest

from demo_web.services.salida_petroleo import enviar_alerta, enviar_alerta_autorizacion

SURTIDOR = "\u26fd\ufe0f"


class PetroleoMailIconoTests(unittest.TestCase):
    def test_salida_y_autorizacion_llevan_el_surtidor(self):
        for fn in (enviar_alerta, enviar_alerta_autorizacion):
            src = inspect.getsource(fn)
            self.assertGreaterEqual(src.count(SURTIDOR), 2, fn.__name__)
            self.assertNotIn("✅", src, fn.__name__)


if __name__ == "__main__":
    unittest.main()
