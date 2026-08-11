#!/bin/sh
set -eu

TEMPLATE="/config/config.template.yaml"
OUT_DIR="/root/.config/mihomo"
OUT="${OUT_DIR}/config.yaml"

if [ -z "${PROXY_SUB_URL:-}" ]; then
  echo "PROXY_SUB_URL is empty — set it in .env / GitHub secret ENV_FILE"
  exit 1
fi

mkdir -p "${OUT_DIR}/providers"
# Escape sed special chars in URL (& and \)
SAFE_URL=$(printf '%s' "$PROXY_SUB_URL" | sed -e 's/[&\\]/\\&/g')
sed "s|__PROXY_SUB_URL__|${SAFE_URL}|g" "$TEMPLATE" > "$OUT"

echo "mihomo config ready, starting..."
exec mihomo -d "$OUT_DIR"
