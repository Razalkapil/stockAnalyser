#!/usr/bin/env bash
# Restore a backup into the live data directory.
#   deploy/restore.sh /srv/stockanalyser/backups/2026-09-18
# Stops the services, restores (moving what was there aside -- nothing is deleted), migrates,
# runs the doctor, and starts the services again. Needs sudo.
set -euo pipefail

BACKUP="${1:?usage: restore.sh <backup-directory>}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STK="${STK:-$APP_DIR/.venv/bin/stk}"

"$STK" backup verify "$BACKUP"

sudo systemctl stop stk-api.service stk-poller.service stk-nightly.timer stk-weekly.timer
trap 'sudo systemctl start stk-api.service stk-poller.service stk-nightly.timer stk-weekly.timer' EXIT

sudo -u stk env STK_APP__ENV="${STK_APP__ENV:-prod}" "$STK" backup restore "$BACKUP" --yes --force
sudo -u stk env STK_APP__ENV="${STK_APP__ENV:-prod}" "$STK" db migrate
sudo -u stk env STK_APP__ENV="${STK_APP__ENV:-prod}" "$STK" doctor || \
    echo "doctor reported problems (see above) -- the restore itself completed." >&2
echo "Restored from $BACKUP. Previous data was moved aside as *.pre-restore-* -- delete it once you are satisfied."
