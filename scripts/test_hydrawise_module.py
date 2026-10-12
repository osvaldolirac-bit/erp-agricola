#!/usr/bin/env python3
"""Smoke tests estáticos del módulo Hydrawise (sin API key)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from demo_web.services.hydrawise_client import (
        assess_field_connectivity,
        assess_relay_schedule_liveness,
        flatten_relays,
        parse_last_contact_ts,
        relay_status_map,
    )

    sample = {
        "controllers": [
            {
                "relays": [
                    {"relay_id": 10, "name": "North"},
                    {"relay_id": 11, "name": "South"},
                ]
            }
        ]
    }
    relays = flatten_relays(sample)
    assert len(relays) == 2 and relays[0]["relay_id"] == 10

    st = {"relays": [{"relay_id": 10, "running": 1}]}
    mp = relay_status_map(st)
    assert mp[10]["running"] is True

    assert parse_last_contact_ts("1685384004") == 1685384004.0
    base = 1685384004.0
    on = assess_field_connectivity(
        {"last_contact": "1685384004", "status": "Online"},
        now_ts=base + 900,
    )
    assert on["equipment_online"] is True
    off = assess_field_connectivity(
        {"last_contact": "1685384004", "status": "Online"},
        now_ts=base + 2000,
    )
    assert off["equipment_online"] is False

    assert assess_relay_schedule_liveness(
        {"relays": [{"time": 1576800000, "run": 0}] * 3}
    ) is False
    assert assess_relay_schedule_liveness(
        {"relays": [{"time": 3600, "run": 0}, {"time": 120, "run": 0}]}
    ) is True

    for name in (
        "demo_web/services/hydrawise_riego.py",
        "demo_web/services/registro_riego.py",
        "demo_web/services/native/riego.py",
    ):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "registrar_desde_hydrawise" in src or "hydrawise" in src

    hw = (ROOT / "demo_web/services/hydrawise_riego.py").read_text(encoding="utf-8")
    assert "fert_json" in hw and "parse_cola_lineas_form" in hw
    assert "estado_conexion_controlador" in hw
    assert "contexto_control_hydra_ui" in hw
    rr = (ROOT / "demo_web/services/registro_riego.py").read_text(encoding="utf-8")
    assert "confirmar_fert_hydra" in rr and "fert_estado" in rr

    print("test_hydrawise_module: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
