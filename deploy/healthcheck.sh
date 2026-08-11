#!/usr/bin/env bash
# Проверка, что контейнер жив и Telegram API доступен с сервера (через прокси).
set -euo pipefail

APP_DIR="${1:-.}"
cd "$APP_DIR"

echo "== docker compose ps =="
docker compose ps -a || true

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-proxy; then
  echo "::error::Контейнер stalzone-proxy не running — без него Telegram с VPS не достучится"
  docker compose logs --tail 80 proxy || true
  exit 1
fi

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-monitor; then
  echo "::error::Контейнер stalzone-monitor не в статусе running"
  echo "== recent logs =="
  docker compose logs --tail 120 || true
  exit 1
fi

echo "== recent logs (proxy) =="
docker compose logs --tail 40 proxy || true
echo "== recent logs (monitor) =="
docker compose logs --tail 80 monitor || true

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

if [[ -z "${PROXY_SUB_URL:-}" ]]; then
  echo "::error::PROXY_SUB_URL пустой — добавь ссылку VPN-подписки в ENV_FILE"
  exit 1
fi

# С хоста ходим в прокси только на localhost (порт проброшен как 127.0.0.1:7890)
PROXY_URL="${HTTPS_PROXY:-http://127.0.0.1:7890}"
case "$PROXY_URL" in
  *://proxy:*) PROXY_URL="http://127.0.0.1:7890" ;;
esac

CURL=(curl -sS --max-time 30 -x "$PROXY_URL")
echo "Прокси для проверки: $PROXY_URL"

echo "== wait for proxy / telegram =="
OK=0
for i in $(seq 1 36); do
  TG_HTTP="$("${CURL[@]}" -o /tmp/tg-root.body -w "%{http_code}" https://api.telegram.org/ || true)"
  echo "try $i: api.telegram.org HTTP=${TG_HTTP}"
  if [[ "$TG_HTTP" =~ ^[23] ]]; then
    OK=1
    break
  fi
  sleep 5
done

if [[ "$OK" -ne 1 ]]; then
  echo "::error::Через прокси api.telegram.org всё ещё недоступен. Проверь PROXY_SUB_URL / ноды VPN."
  docker compose logs --tail 100 proxy || true
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
    echo "::error::API жив, но sendMessage админу упал (HTTP ${SEND_HTTP}). Проверь TELEGRAM_CHAT_ID."
    exit 1
  fi
fi

echo "HEALTH_OK"
