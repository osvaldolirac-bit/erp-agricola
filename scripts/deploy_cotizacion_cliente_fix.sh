#!/usr/bin/env bash
# Despliega fix: cotización no debe cambiar de cliente al guardar/cambiar estado.
set -euo pipefail

ROOT="${RIOMAIPO_ROOT:-/root/riomaipo}"
REPO="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

cp "$REPO/riomaipo_vps/rmweb/app.py" "$ROOT/rmweb/app.py"
cp "$REPO/riomaipo_vps/rmweb/templates/cotizaciones/form.html" "$ROOT/rmweb/templates/cotizaciones/form.html"

if systemctl is-active --quiet erp-riomaipo; then
  systemctl restart erp-riomaipo
fi

echo "Deploy cotización cliente fix OK → $ROOT"
