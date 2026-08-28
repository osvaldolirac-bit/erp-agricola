#!/usr/bin/env bash
# deploy-demo-web.sh — despliegue seguro rubro agrícola (demo-web, :8508)
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/root/demo-web}"
SOURCE_ROOT="${SOURCE_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/backups/demo-web}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BK="${BACKUP_ROOT}/${STAMP}"
SERVICE="${SERVICE:-erp-agricola-web}"
PORT="${PORT:-8508}"
VERIFY_SCRIPT="${VERIFY_SCRIPT:-/root/scripts/verify_agricola.py}"
PREFIX="${PREFIX:-/agricola}"

log() { echo "[$(date -Iseconds)] $*"; }
die() { log "ERROR: $*"; exit 1; }

rollback() {
  if [[ ! -d "$BK/code" ]]; then
    log "No backup at $BK — cannot rollback"
    return 1
  fi
  log "ROLLBACK from $BK"
  rsync -a "$BK/code/" "$DEPLOY_ROOT/"
  systemctl restart "$SERVICE" || true
}

trap 'if [[ $? -ne 0 ]]; then log "Deploy failed — attempting rollback"; rollback; fi' EXIT

log "=== Demo-web agrícola deploy ==="
log "Source: $SOURCE_ROOT"
log "Target: $DEPLOY_ROOT"

[[ -d "$SOURCE_ROOT/demo_web" ]] || die "missing demo_web in $SOURCE_ROOT"
[[ -d "$DEPLOY_ROOT" ]] || die "missing $DEPLOY_ROOT"
command -v rsync >/dev/null || die "rsync required"
command -v systemctl >/dev/null || die "systemctl required"

# 1. Backup
log "Backup → $BK"
mkdir -p "$BK"
rsync -a "$DEPLOY_ROOT/" "$BK/code/" --exclude '.venv' --exclude '__pycache__' --exclude '*.db'
[[ -f /etc/systemd/system/${SERVICE}.service ]] && cp -a "/etc/systemd/system/${SERVICE}.service" "$BK/"
log "Backup OK"

# 2. Sync demo_web (templates, static, services, blueprints)
RSYNC_EXCLUDES=(--exclude '__pycache__' --exclude '*.db' --exclude '*.pyc')
log "Sync demo_web/"
rsync -a "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_ROOT/demo_web/" "$DEPLOY_ROOT/demo_web/"

# Scripts de verificación
if [[ -f "$SOURCE_ROOT/scripts/verify_agricola.py" ]]; then
  mkdir -p /root/scripts
  cp -a "$SOURCE_ROOT/scripts/verify_agricola.py" /root/scripts/verify_agricola.py
  chmod +x /root/scripts/verify_agricola.py 2>/dev/null || true
fi

if [[ -f "$SOURCE_ROOT/requirements.txt" ]] && [[ -x "$DEPLOY_ROOT/.venv/bin/pip" ]]; then
  log "pip install"
  "$DEPLOY_ROOT/.venv/bin/pip" install -r "$SOURCE_ROOT/requirements.txt" -q
fi

# 3. Restart
log "Restart $SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || die "$SERVICE not active"

# 4. Verify
if [[ -f "$VERIFY_SCRIPT" ]]; then
  log "Verify agricola"
  DEMO_WEB_ROOT="$DEPLOY_ROOT/demo_web" \
  BASE_URL="http://127.0.0.1:${PORT}" \
  PREFIX="$PREFIX" \
  python3 "$VERIFY_SCRIPT" || die "verification failed"
else
  log "WARN: verify script not found at $VERIFY_SCRIPT"
  curl -sf "http://127.0.0.1:${PORT}${PREFIX}/login" >/dev/null || die "login check failed"
fi

trap - EXIT
log "Deploy OK — backup: $BK"
log "Rollback manual: rsync -a $BK/code/ $DEPLOY_ROOT/ && systemctl restart $SERVICE"
