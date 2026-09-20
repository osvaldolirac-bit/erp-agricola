#!/usr/bin/env python3
"""Guardia anti-regresión agrícola — falla deploy si se pierden fixes críticos.

Lee /root/demo-web/.erp_regression_manifest.json y valida marcadores en disco.
Registra alertas en /root/erp_status/agricola_alerts.log

Uso:
  python3 regression_guard_agricola.py
  APP_ROOT=/root/demo-web python3 regression_guard_agricola.py --alert
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(os.environ.get("APP_ROOT", "/root/demo-web"))
MANIFEST = APP_ROOT / ".erp_regression_manifest.json"
ALERT_LOG = Path(os.environ.get("ERP_ALERT_LOG", "/root/erp_status/agricola_alerts.log"))
STATUS_FILE = Path(os.environ.get("ERP_STATUS_FILE", "/root/erp_status/agricola_regression.json"))


class RegressionError(Exception):
    pass


def _log_alert(level: str, msg: str, details: list[str]) -> None:
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} [{level}] {msg}"
    if details:
        line += " | " + "; ".join(details[:8])
    with ALERT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    payload = {
        "ts": ts,
        "level": level,
        "ok": level == "OK",
        "message": msg,
        "details": details,
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check_file(rel: str, rules: dict) -> list[str]:
    path = APP_ROOT / rel
    errors: list[str] = []
    if not path.is_file():
        return [f"missing file: {rel}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    min_lines = rules.get("min_lines")
    if min_lines and lines < min_lines:
        errors.append(f"{rel}: only {lines} lines (min {min_lines}) — posible archivo parcial/cortado")
    for needle in rules.get("must_contain", []):
        if needle not in text:
            errors.append(f"{rel}: missing required marker: {needle!r}")
    for forbidden in rules.get("must_not_contain", []):
        if forbidden in text:
            errors.append(f"{rel}: forbidden pattern present: {forbidden!r}")
    return errors


def run_checks(*, write_alert: bool = True) -> list[str]:
    if not MANIFEST.is_file():
        raise RegressionError(f"manifest not found: {MANIFEST}")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = data.get("files") or {}
    all_errors: list[str] = []
    for rel, rules in files.items():
        all_errors.extend(_check_file(rel, rules))
    if write_alert:
        if all_errors:
            _log_alert("CRITICAL", "Regression guard FAILED", all_errors)
        else:
            _log_alert("OK", "Regression guard passed", [])
    return all_errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="solo exit code")
    parser.add_argument("--no-alert", action="store_true", help="no escribir log de alertas")
    args = parser.parse_args()
    try:
        errors = run_checks(write_alert=not args.no_alert)
    except RegressionError as exc:
        if not args.quiet:
            print(f"FAIL regression_guard: {exc}", file=sys.stderr)
        if not args.no_alert:
            _log_alert("CRITICAL", str(exc), [])
        return 2
    if errors:
        if not args.quiet:
            print("REGRESSION GUARD FAILED:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("OK  regression guard — all critical markers present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
