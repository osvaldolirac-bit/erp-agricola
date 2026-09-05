#!/usr/bin/env bash
# Vigilancia periódica agrícola — alerta si verify/regression falla (sin reiniciar).
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/demo-web}"
VERIFY="${VERIFY:-/root/scripts/verify_agricola.py}"
GUARD="${REGRESSION_GUARD:-/root/scripts/regression_guard_agricola.py}"
ALERT_LOG="${ERP_ALERT_LOG:-/root/erp_status/agricola_alerts.log}"
PY="${PY:-$DEPLOY_ROOT/.venv/bin/python3}"

mkdir -p "$(dirname "$ALERT_LOG")"
ts="$(date -Iseconds)"

_run() {
  DEMO_WEB_ROOT="$DEPLOY_ROOT/demo_web" \
  APP_ROOT="$DEPLOY_ROOT" \
  REGRESSION_GUARD="$GUARD" \
  BASE_URL=http://127.0.0.1:8508 \
  PREFIX="" \
  "$PY" "$VERIFY" >/tmp/agricola_health.out 2>&1
}

if _run; then
  echo "$ts [WATCH_OK] verify agricola passed" >> "$ALERT_LOG"
  exit 0
fi

echo "$ts [WATCH_FAIL] verify agricola FAILED — revisar LC/GlobalGAP" >> "$ALERT_LOG"
tail -30 /tmp/agricola_health.out >> "$ALERT_LOG"
echo "---" >> "$ALERT_LOG"
# Alerta visible en status JSON
APP_ROOT="$DEPLOY_ROOT" "$PY" "$GUARD" 2>/dev/null || true
exit 1
