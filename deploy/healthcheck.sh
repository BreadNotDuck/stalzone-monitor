#!/usr/bin/env bash
# Проверка, что контейнер жив и Telegram API доступен с сервера.
set -euo pipefail

APP_DIR="${1:-.}"
cd "$APP_DIR"

echo "== docker compose ps =="
docker compose ps -a || true

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-monitor; then
  echo "::error::Контейнер stalzone-monitor не в статусе running"
  echo "== recent logs =="
  docker compose logs --tail 120 || true
  exit 1
fi

echo "== recent logs =="
docker compose logs --tail 80 || true

if [[ ! -f .env ]]; then
  echo "::error::Файл .env отсутствует на VPS"
  exit 1
fi

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
source .env
set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "::error::TELEGRAM_BOT_TOKEN пустой в .env на VPS"
  exit 1
fi

CURL=(curl -sS --max-time 25)
if [[ -n "${HTTPS_PROXY:-}" ]]; then
  CURL+=(-x "$HTTPS_PROXY")
  echo "Прокси: HTTPS_PROXY задан"
elif [[ -n "${HTTP_PROXY:-}" ]]; then
  CURL+=(-x "$HTTP_PROXY")
  echo "Прокси: HTTP_PROXY задан"
else
  echo "Прокси: не задан"
fi

echo "== ping api.telegram.org =="
TG_HTTP="$("${CURL[@]}" -o /tmp/tg-root.body -w "%{http_code}" https://api.telegram.org/ || true)"
echo "api.telegram.org HTTP=${TG_HTTP}"
if [[ ! "$TG_HTTP" =~ ^[23] ]]; then
  echo "::error::С VPS недоступен api.telegram.org (HTTP ${TG_HTTP:-000}). Нужен рабочий HTTPS_PROXY в секрете ENV_FILE."
  exit 1
fi

echo "== getMe =="
ME_HTTP="$("${CURL[@]}" -o /tmp/tg-me.json -w "%{http_code}" "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" || true)"
echo "getMe HTTP=${ME_HTTP}"
cat /tmp/tg-me.json || true
echo

if [[ "$ME_HTTP" != "200" ]]; then
  echo "::error::Telegram getMe не 200 (HTTP ${ME_HTTP}). Токен битый или API режется."
  exit 1
fi

if ! grep -q '"ok":true' /tmp/tg-me.json; then
  echo "::error::Telegram getMe вернул ok!=true — проверь TELEGRAM_BOT_TOKEN"
  exit 1
fi

# Пробуем доставить тестовое сообщение админу (если chat_id есть)
if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "== sendMessage smoke =="
  SEND_HTTP="$("${CURL[@]}" -o /tmp/tg-send.json -w "%{http_code}" \
    -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H 'Content-Type: application/json' \
    -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"✅ Healthcheck: бот на VPS отвечает $(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
    || true)"
  echo "sendMessage HTTP=${SEND_HTTP}"
  cat /tmp/tg-send.json || true
  echo
  if [[ "$SEND_HTTP" != "200" ]]; then
    echo "::error::Контейнер есть, API жив, но sendMessage админу упал (HTTP ${SEND_HTTP}). Проверь TELEGRAM_CHAT_ID."
    exit 1
  fi
fi

echo "HEALTH_OK"
