#!/usr/bin/env bash
# One-time setup on the VM (Ubuntu 24.04). Run as a sudo-capable user from the repo checkout at
# /srv/stockanalyser/app. Idempotent. See docs/runbook.md for the whole procedure.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$APP_DIR" == /srv/stockanalyser/app ]] || {
    echo "expected the checkout at /srv/stockanalyser/app (found $APP_DIR); the unit files assume it" >&2
    exit 1
}

command -v uv >/dev/null || { echo "uv is not on PATH -- install it first (https://docs.astral.sh/uv/)" >&2; exit 1; }
id stk >/dev/null 2>&1 || sudo useradd --system --home /srv/stockanalyser --shell /usr/sbin/nologin stk
sudo mkdir -p /srv/stockanalyser/data /srv/stockanalyser/backups /etc/stockanalyser
sudo chown -R stk:stk /srv/stockanalyser/data /srv/stockanalyser/backups
sudo chown -R stk:stk "$APP_DIR"

if [[ ! -f /etc/stockanalyser/env ]]; then
    sudo install -m 600 -o root -g stk "$APP_DIR/deploy/env.example" /etc/stockanalyser/env
    echo "Created /etc/stockanalyser/env -- edit it (ANTHROPIC_API_KEY, backup settings)."
fi

sudo -u stk bash -c "cd '$APP_DIR' && uv sync --frozen"
sudo -u stk bash -c "cd '$APP_DIR' && set -a && . /etc/stockanalyser/env && set +a && .venv/bin/stk db migrate"

sudo install -m 644 "$APP_DIR"/deploy/systemd/*.service "$APP_DIR"/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stk-api.service stk-poller.service \
    stk-nightly.timer stk-weekly.timer stk-backup.timer stk-doctor.timer
echo "Installed. Next: build the web app, install Caddy with deploy/Caddyfile, create an API token."
