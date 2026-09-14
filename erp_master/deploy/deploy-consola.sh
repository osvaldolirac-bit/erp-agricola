#!/usr/bin/env bash
# deploy-consola.sh — despliegue seguro Super Consola (backup + verify + rollback)
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/erp_master}"
SOURCE_ROOT="${SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/backups/erp_master}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="${BACKUP_ROOT}/${STAMP}"
SERVICE="${SERVICE:-erp-master-web}"
PORT="${PORT:-8507}"
VERIFY_SCRIPT="${VERIFY_SCRIPT:-/root/scripts/verify_consola.py}"
SYNC_APP="${SYNC_APP:-0}"

log() { echo "[$(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; exit 1; }

rollback() {
  if [[ ! -d "$BK/code" ]]; then
    log "No backup at $BK — cannot rollback"
    return 1
  fi
  log "ROLLBACK from $BK"
  rsync -a "$BK/code/" "$DEPLOY_ROOT/"
  [[ -f "$BK/erp_master.db" ]] && cp -a "$BK/erp_master.db" /root/erp_master.db
  systemctl restart "$SERVICE" || true
}

trap 'if [[ $? -ne 0 ]]; then log "Deploy failed — attempting rollback"; rollback; fi' EXIT

log "=== Super Consola deploy ==="
log "Source: $SOURCE_ROOT"
log "Target: $DEPLOY_ROOT"

[[ -d "$SOURCE_ROOT/erp_master" ]] || die "missing source erp_master in $SOURCE_ROOT"
[[ -d "$DEPLOY_ROOT" ]] || die "missing $DEPLOY_ROOT"
command -v rsync >/dev/null || die "rsync required"
command -v systemctl >/dev/null || die "systemctl required"

# 1. Backup
log "Backup → $BK"
mkdir -p "$BK"
rsync -a "$DEPLOY_ROOT/" "$BK/code/" --exclude '.venv' --exclude '__pycache__'
[[ -f /root/erp_master.db ]] && cp -a /root/erp_master.db "$BK/"
[[ -f /etc/systemd/system/${SERVICE}.service ]] && cp -a "/etc/systemd/system/${SERVICE}.service" "$BK/"
log "Backup OK"

# 2. Sync safe paths (never blind overwrite app.py / tenant_admin.py unless SYNC_APP=1)
RSYNC_EXCLUDES=(--exclude '.venv' --exclude '__pycache__' --exclude '*.db')
log "Sync templates, static, config, wsgi"
rsync -a "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_ROOT/erp_master/erp_master/templates/" "$DEPLOY_ROOT/erp_master/templates/"
rsync -a "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_ROOT/erp_master/erp_master/static/" "$DEPLOY_ROOT/erp_master/static/"
rsync -a "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_ROOT/erp_master/wsgi.py" "$DEPLOY_ROOT/wsgi.py"
rsync -a "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_ROOT/erp_master/erp_master/config.py" "$DEPLOY_ROOT/erp_master/config.py"

if [[ "$SYNC_APP" == "1" ]]; then
  log "SYNC_APP=1 — syncing app.py and tenant_admin.py (explicit)"
  rsync -a "${RSYNC_EXCLUDES[@]}" \
    "$SOURCE_ROOT/erp_master/erp_master/app.py" "$DEPLOY_ROOT/erp_master/app.py"
  rsync -a "${RSYNC_EXCLUDES[@]}" \
    "$SOURCE_ROOT/erp_master/erp_master/tenant_admin.py" "$DEPLOY_ROOT/erp_master/tenant_admin.py"
else
  log "Skipping app.py / tenant_admin.py (set SYNC_APP=1 to overwrite)"
fi

# 3. Dependencies
if [[ -f "$DEPLOY_ROOT/requirements.txt" ]] && [[ -x "$DEPLOY_ROOT/.venv/bin/pip" ]]; then
  log "pip install"
  "$DEPLOY_ROOT/.venv/bin/pip" install -r "$DEPLOY_ROOT/requirements.txt" -q
fi

# 4. Restart
log "Restart $SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || die "$SERVICE not active"

# 5. Verify
if [[ -f "$VERIFY_SCRIPT" ]]; then
  log "Verify"
  ERP_MASTER_ROOT="$DEPLOY_ROOT" python3 "$VERIFY_SCRIPT" || die "verification failed"
else
  log "WARN: verify script not found at $VERIFY_SCRIPT"
  curl -sf "http://127.0.0.1:${PORT}/health" | grep -q '"ok"' || die "health check failed"
fi

trap - EXIT
log "Deploy OK — backup: $BK"
log "Rollback manual: rsync -a $BK/code/ $DEPLOY_ROOT/ && systemctl restart $SERVICE"
