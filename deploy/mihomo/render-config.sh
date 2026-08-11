#!/usr/bin/env bash
# Собирает конфиг mihomo из шаблона + PROXY_SUB_URL в .env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/.env}"
TEMPLATE="$ROOT/deploy/mihomo/config.template.yaml"
OUT_DIR="$ROOT/deploy/mihomo/runtime"
OUT="$OUT_DIR/config.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Нет $ENV_FILE"
  exit 1
fi

PROXY_SUB_URL="$(grep -E '^PROXY_SUB_URL=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r')"
if [[ -z "$PROXY_SUB_URL" ]]; then
  echo "PROXY_SUB_URL пустой в $ENV_FILE"
  exit 1
fi

mkdir -p "$OUT_DIR/providers"
SAFE_URL="$(printf '%s' "$PROXY_SUB_URL" | sed -e 's/[&\\]/\\&/g')"
sed "s|__PROXY_SUB_URL__|${SAFE_URL}|g" "$TEMPLATE" > "$OUT"
echo "mihomo config -> $OUT"
