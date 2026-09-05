#!/usr/bin/env bash
# deploy-demo-web.sh — despliegue agrícola con verify LC + Espino obligatorio
#
# Procedimiento único en VPS (NO scp suelto):
#   cd /root/demo-web-src && git pull
#   bash vps-robust/scripts/deploy-demo-web.sh
#
# Si verify_espino falla, el deploy hace rollback automático.
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/demo-web}"
SOURCE_ROOT="${SOURCE_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/backups/demo-web}"
SCRIPTS_ROOT="${SCRIPTS_ROOT:-/root/scripts}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="${BACKUP_ROOT}/${STAMP}"
SERVICE="${SERVICE:-erp-agricola-web}"
PORT="${PORT:-8508}"
VERIFY_AGRICOLA="${VERIFY_AGRICOLA:-${SCRIPTS_ROOT}/verify_agricola.py}"
VERIFY_ESPINO="${VERIFY_ESPINO:-${SCRIPTS_ROOT}/verify_espino.py}"
ENSURE_ESPINO="${ENSURE_ESPINO:-${SCRIPTS_ROOT}/ensure_espino_operativo.py}"

log() { echo "[$(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; exit 1; }

rollback() {
  if [[ ! -d "$BK/code" ]]; then
    log "No backup at $BK — cannot rollback"
    return 1
  fi
  log "ROLLBACK from $BK"
  rsync -a "$BK/code/" "$DEPLOY_ROOT/"
  systemctl restart "$SERVICE" 2>/dev/null || true
}

trap 'if [[ $? -ne 0 ]]; then log "Deploy failed — attempting rollback"; rollback; fi' EXIT

log "=== demo-web deploy (LC + Espino verify) ==="
log "Source: $SOURCE_ROOT"
log "Target: $DEPLOY_ROOT"

[[ -d "$SOURCE_ROOT/demo_web" ]] || die "missing demo_web in $SOURCE_ROOT"
[[ -d "$DEPLOY_ROOT" ]] || die "missing $DEPLOY_ROOT"
command -v rsync >/dev/null || die "rsync required"
command -v systemctl >/dev/null || die "systemctl required"

# 1. Backup
log "Backup → $BK"
mkdir -p "$BK"
rsync -a "$DEPLOY_ROOT/" "$BK/code/" \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.db'
log "Backup OK"

# 2. Sync código agrícola
RSYNC_EX=(--exclude '.venv' --exclude '__pycache__' --exclude '*.db')
log "Sync demo_web + app_concepcion + erp modules"
rsync -a "${RSYNC_EX[@]}" "$SOURCE_ROOT/demo_web/" "$DEPLOY_ROOT/demo_web/"
[[ -f "$SOURCE_ROOT/demo-web/app_concepcion.py" ]] && \
  rsync -a "$SOURCE_ROOT/demo-web/app_concepcion.py" "$DEPLOY_ROOT/app_concepcion.py"
[[ -f "$SOURCE_ROOT/demo-web/erp_flujo_financiero.py" ]] && \
  rsync -a "$SOURCE_ROOT/demo-web/erp_flujo_financiero.py" "$DEPLOY_ROOT/erp_flujo_financiero.py"
for f in erp_proveedores.py erp_inventario_ia.py; do
  [[ -f "$SOURCE_ROOT/demo-web/$f" ]] && rsync -a "$SOURCE_ROOT/demo-web/$f" "$DEPLOY_ROOT/$f"
done

# 3. Scripts operativos → /root/scripts (verify, ensure, cron)
log "Sync scripts → $SCRIPTS_ROOT"
mkdir -p "$SCRIPTS_ROOT"
for s in verify_agricola.py verify_espino.py ensure_espino_operativo.py \
         respaldo_cron_tenants.py bootstrap_espino_tenant.py; do
  src=""
  if [[ -f "$SOURCE_ROOT/scripts/$s" ]]; then
    src="$SOURCE_ROOT/scripts/$s"
  elif [[ -f "$SOURCE_ROOT/vps-robust/scripts/$s" ]]; then
    src="$SOURCE_ROOT/vps-robust/scripts/$s"
  fi
  if [[ -n "$src" ]]; then
    rsync -a "$src" "$SCRIPTS_ROOT/$s"
    chmod +x "$SCRIPTS_ROOT/$s" 2>/dev/null || true
  fi
done
[[ -f "$SOURCE_ROOT/vps-robust/scripts/regression_guard_agricola.py" ]] && \
  rsync -a "$SOURCE_ROOT/vps-robust/scripts/regression_guard_agricola.py" "$SCRIPTS_ROOT/"

# 4. Dependencias
if [[ -f "$DEPLOY_ROOT/requirements.txt" ]] && [[ -x "$DEPLOY_ROOT/.venv/bin/pip" ]]; then
  log "pip install"
  "$DEPLOY_ROOT/.venv/bin/pip" install -r "$DEPLOY_ROOT/requirements.txt" -q
fi

# 5. Reparar estado Espino (flags, cron) antes de verify
log "ensure_espino_operativo"
APP_ROOT="$DEPLOY_ROOT" python3 "$ENSURE_ESPINO"

# 6. Restart
log "Restart $SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || die "$SERVICE not active"

# 7. Verify LC (no regresión)
log "verify_agricola"
APP_ROOT="$DEPLOY_ROOT" DEMO_WEB_ROOT="$DEPLOY_ROOT/demo_web" \
  python3 "$VERIFY_AGRICOLA" || die "verify_agricola failed"

# 8. Verify Espino (obligatorio — aborta deploy)
log "verify_espino"
APP_ROOT="$DEPLOY_ROOT" python3 "$VERIFY_ESPINO" || die "verify_espino failed — reglas o CxP Espino rotas"

trap - EXIT
log "Deploy OK"
exit 0
