"""Wrapper unittest para scripts/smoke_robustez.py (CI)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestSmokeRobustez(unittest.TestCase):
    def test_smoke_script(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/smoke_robustez.py")],
            cwd=str(ROOT),
            env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_deploy_manifest_completo(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/deploy_robustez_lc_espino_vps.py"), "--check"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
