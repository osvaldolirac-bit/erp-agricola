#!/usr/bin/env bash
# Git pre-commit — bloquea commits que rompen paridad LC/Espino.
set -euo pipefail

ROOT="${APP_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo /root/demo-web)}"
PY="${PYTHON:-python3}"
VERIFY="${ROOT}/scripts/verify_tenant_parity.py"

changed="$(git diff --cached --name-only 2>/dev/null || true)"
echo "$changed" | grep -qE \
  'demo_web/services/tenant_rules|demo_web/services/tesoreria_cxp|demo_web/services/lc_excluir_espino|demo_web/services/native/flujo|demo_web/services/native/tesoreria|demo_web/services/branding|demo_web/app\.py|demo_web/tenants\.py|scripts/verify_espino|scripts/test_tenant' \
  || exit 0

[[ -f "$VERIFY" ]] || exit 0

APP_ROOT="$ROOT" "$PY" "$VERIFY" || {
  echo "" >&2
  echo "COMMIT BLOQUEADO — paridad tenant LC/Espino rota." >&2
  echo "  Ver: demo_web/services/tenant_rules.py y vps-robust/TENANT_PARITY.md" >&2
  exit 1
}
