#!/usr/bin/env bash
# Nightly backup: app.db (consistent snapshot) + the parquet lake, verified, rotated, then
# optionally copied off the box. Exits non-zero if ANY part fails, so the systemd unit fails and
# `systemctl --failed` / `stk doctor` show it. Safe to run by hand.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STK="${STK:-$APP_DIR/.venv/bin/stk}"
DEST="${STK_BACKUP_DEST:-/srv/stockanalyser/backups}"

"$STK" backup run --dest "$DEST"

if [[ -n "${STK_OFFSITE_CMD:-}" ]]; then
    echo "off-box copy: $STK_OFFSITE_CMD"
    bash -c "$STK_OFFSITE_CMD"
else
    echo "WARNING: STK_OFFSITE_CMD is not set -- this backup exists only on this machine." >&2
fi
