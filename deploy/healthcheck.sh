#!/usr/bin/env bash
# Проверка: proxy+monitor running и Telegram доступен через локальный mihomo.
set -euo pipefail

APP_DIR="${1:-.}"
cd "$APP_DIR"

echo "== docker compose ps =="
docker compose ps -a || true

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-proxy; then
  echo "::error::Контейнер stalzone-proxy не running"
  docker compose logs --tail 120 proxy || true
  exit 1
fi

if ! docker compose ps --status running 2>/dev/null | grep -q stalzone-monitor; then
  echo "::error::Контейнер stalzone-monitor не running"
  docker compose logs --tail 120 monitor || true
  exit 1
fi

echo "== recent logs =="
docker compose logs --tail 60 proxy || true
docker compose logs --tail 60 monitor || true

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

PROXY_URL="http://127.0.0.1:7890"
CURL=(curl -sS --max-time 30 -x "$PROXY_URL")
echo "Прокси для проверки: $PROXY_URL"

echo "== wait for telegram via proxy =="
OK=0
for i in $(seq 1 40); do
  TG_HTTP="$("${CURL[@]}" -o /tmp/tg-root.body -w "%{http_code}" https://api.telegram.org/ || true)"
  echo "try $i: api.telegram.org HTTP=${TG_HTTP}"
  if [[ "$TG_HTTP" =~ ^[23] ]]; then
    OK=1
    break
  fi
  sleep 5
done

if [[ "$OK" -ne 1 ]]; then
  echo "::error::Через mihomo api.telegram.org недоступен. Ноды VPN мертвы или конфиг битый."
  docker compose logs --tail 150 proxy || true
  exit 1
fi

echo "== getMe =="
ME_HTTP="$("${CURL[@]}" -o /tmp/tg-me.json -w "%{http_code}" "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" || true)"
echo "getMe HTTP=${ME_HTTP}"
cat /tmp/tg-me.json || true
echo
if [[ "$ME_HTTP" != "200" ]] || ! grep -q '"ok":true' /tmp/tg-me.json; then
  echo "::error::Telegram getMe failed (HTTP ${ME_HTTP})"
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
    echo "::error::sendMessage админу упал (HTTP ${SEND_HTTP})"
    exit 1
  fi
fi

echo "HEALTH_OK"
