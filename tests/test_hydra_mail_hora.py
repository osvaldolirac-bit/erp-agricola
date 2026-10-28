"""El correo de inicio HYDRA muestra la hora de Santiago y la gota de riego."""
from __future__ import annotations

import inspect
import unittest

from demo_web.services import registro_riego as rr
from demo_web.services.registro_riego import inicio_visible_mail


class HydraMailHoraTests(unittest.TestCase):
    def test_programar_muestra_la_hora_elegida(self):
        self.assertEqual(
            inicio_visible_mail("programado", "2026-10-28 20:15:00"),
            "2026-10-28 20:15",
        )

    def test_regar_ahora_en_verano_suma_la_hora_de_santiago(self):
        # hora_chile() guarda UTC−4. El 28 oct 2026 Santiago está en UTC−3.
        self.assertEqual(
            inicio_visible_mail("run_now", "2026-10-28 18:44:08"),
            "2026-10-28 19:44",
        )

    def test_regar_ahora_en_invierno_no_mueve_la_hora(self):
        # En julio Santiago también está en UTC−4.
        self.assertEqual(
            inicio_visible_mail("run_now", "2026-07-15 18:44:08"),
            "2026-07-15 18:44",
        )

    def test_los_correos_de_riego_llevan_la_gota(self):
        for fn in (
            rr.enviar_alerta,
            rr.enviar_alerta_hydra_sector_ok,
            rr.enviar_alerta_hydra_cola_inicio,
            rr.enviar_alerta_hydra_interrupcion,
        ):
            src = inspect.getsource(fn)
            self.assertIn("💧", src, fn.__name__)
            self.assertIn("asunto = f\"💧", src, fn.__name__)


if __name__ == "__main__":
    unittest.main()
