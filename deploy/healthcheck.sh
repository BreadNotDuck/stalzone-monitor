#!/usr/bin/env bash
# Healthcheck: контейнер running + Telegram API (напрямую или через локальный proxy).
set -euo pipefail

APP_DIR="${1:-.}"
cd "$APP_DIR"

echo "== docker compose ps =="
docker compose ps -a || true

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-monitor; then
  echo "::error::Контейнер stalzone-monitor не running"
  docker compose logs --tail 120 monitor || true
  exit 1
fi

echo "== recent logs =="
docker compose logs --tail 80 monitor || true

if [[ ! -f .env ]]; then
  echo "::error::Файл .env отсутствует на VPS"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "::error::TELEGRAM_BOT_TOKEN пустой в .env"
  exit 1
fi

CURL=(curl -sS --max-time 25)
PROXY_URL="${HTTPS_PROXY:-}"
if [[ -n "$PROXY_URL" ]]; then
  case "$PROXY_URL" in
    *://proxy:*) PROXY_URL="http://127.0.0.1:7890" ;;
  esac
  CURL+=(-x "$PROXY_URL")
  echo "Прокси: $PROXY_URL"
else
  echo "Прокси: нет (прямой доступ)"
fi

echo "== telegram =="
TG_HTTP="$("${CURL[@]}" -o /tmp/tg-root.body -w "%{http_code}" https://api.telegram.org/ || true)"
echo "api.telegram.org HTTP=${TG_HTTP}"
if [[ ! "$TG_HTTP" =~ ^[23] ]]; then
  echo "::error::api.telegram.org недоступен с VPS (HTTP ${TG_HTTP:-000})"
  exit 1
fi

ME_HTTP="$("${CURL[@]}" -o /tmp/tg-me.json -w "%{http_code}" "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" || true)"
echo "getMe HTTP=${ME_HTTP}"
cat /tmp/tg-me.json || true
echo
if [[ "$ME_HTTP" != "200" ]] || ! grep -q '"ok":true' /tmp/tg-me.json; then
  echo "::error::Telegram getMe failed (HTTP ${ME_HTTP})"
  exit 1
fi

if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  SEND_HTTP="$("${CURL[@]}" -o /tmp/tg-send.json -w "%{http_code}" \
    -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H 'Content-Type: application/json' \
    -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"✅ Healthcheck: бот на VPS отвечает $(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
    || true)"
  echo "sendMessage HTTP=${SEND_HTTP}"
  cat /tmp/tg-send.json || true
  echo
  if [[ "$SEND_HTTP" != "200" ]]; then
    echo "::error::sendMessage админу упал (HTTP ${SEND_HTTP})"
    exit 1
  fi
fi

echo "HEALTH_OK"
