#!/usr/bin/env bash
# Однократная подготовка VPS под GitHub Actions (Docker + каталог).
set -euo pipefail

APP_DIR="${1:-/opt/stalzone-monitor}"

apt-get update
apt-get install -y ca-certificates curl git
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

mkdir -p "$APP_DIR/data"
chown -R "${SUDO_USER:-root}:${SUDO_USER:-root}" "$APP_DIR" 2>/dev/null || true

echo "VPS готов. Добавь в GitHub Secrets:"
echo "  VPS_HOST, VPS_USER, VPS_SSH_KEY, VPS_APP_DIR=$APP_DIR"
echo "  ENV_FILE — содержимое .env (многострочный secret)"
echo ""
echo "Публичный ключ для GitHub Actions (добавь в authorized_keys):"
echo "  (сгенерируй пару deploy-ключей и положи private key в VPS_SSH_KEY)"
