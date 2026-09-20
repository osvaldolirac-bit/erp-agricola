#!/usr/bin/env bash
# Chequeos agrícola completos (local o VPS). Exit 1 = no desplegar.
set -euo pipefail

ROOT="${APP_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export APP_ROOT="$ROOT"
PY="${PYTHON:-python3}"

echo "=== verify_tenant_parity (reglas LC/Espino) ==="
"$PY" "$ROOT/scripts/verify_tenant_parity.py"

if [[ -f "$ROOT/vps-robust/scripts/verify_agricola.py" ]]; then
  echo "=== verify_agricola (LC anti-regresión) ==="
  DEMO_WEB_ROOT="$ROOT/demo_web" "$PY" "$ROOT/vps-robust/scripts/verify_agricola.py" || true
fi

if [[ -f /root/espino/erp_espino.db ]]; then
  echo "=== verify_espino (VPS) ==="
  "$PY" "$ROOT/scripts/verify_espino.py"
fi

echo "=== OK ==="
