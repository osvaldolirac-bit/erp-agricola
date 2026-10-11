#!/usr/bin/env python3
"""Smoke tests estáticos del módulo Hydrawise (sin API key)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from demo_web.services.hydrawise_client import flatten_relays, relay_status_map

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

    for name in (
        "demo_web/services/hydrawise_riego.py",
        "demo_web/services/registro_riego.py",
        "demo_web/services/native/riego.py",
    ):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "registrar_desde_hydrawise" in src or "hydrawise" in src

    print("test_hydrawise_module: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
