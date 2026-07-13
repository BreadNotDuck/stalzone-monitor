#!/usr/bin/env bash
# Первичная установка на Ubuntu/Debian VPS (без Docker).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/stalzone-monitor}"
APP_USER="${APP_USER:-stalzone}"

if [[ $EUID -ne 0 ]]; then
  echo "Запусти от root: sudo bash deploy/install-vps.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip git ca-certificates

id "$APP_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

mkdir -p "$APP_DIR"
rsync -a --exclude .venv --exclude data --exclude .git ./ "$APP_DIR/" 2>/dev/null || cp -a . "$APP_DIR/"

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p data
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

cp deploy/systemd/stalzone-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable stalzone-monitor
systemctl restart stalzone-monitor

echo "Готово. Логи: journalctl -u stalzone-monitor -f"
