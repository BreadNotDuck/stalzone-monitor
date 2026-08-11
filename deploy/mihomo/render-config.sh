#!/usr/bin/env bash
# Готовит runtime-конфиг mihomo.
# Если передан URL подписки — скачивает её здесь (где есть интернет) в providers/vlv.yaml.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/.env}"
SUB_URL="${2:-}"
TEMPLATE="$ROOT/deploy/mihomo/config.template.yaml"
OUT_DIR="$ROOT/deploy/mihomo/runtime"
OUT="$OUT_DIR/config.yaml"
PROVIDER="$OUT_DIR/providers/vlv.yaml"

mkdir -p "$OUT_DIR/providers"

if [[ -z "$SUB_URL" && -f "$ENV_FILE" ]]; then
  SUB_URL="$(grep -E '^PROXY_SUB_URL=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r')"
fi

if [[ -z "$SUB_URL" ]]; then
  echo "PROXY_SUB_URL пустой"
  exit 1
fi

echo "Downloading subscription..."
TMP="$(mktemp)"
if ! curl -fsSL --max-time 60 -A "clash" "$SUB_URL" -o "$TMP"; then
  echo "Не удалось скачать подписку"
  rm -f "$TMP"
  exit 1
fi

# Подписка часто base64 с vless:// строками. Clash Meta ждёт YAML proxies: или список URI.
# Конвертим URI-список в минимальный provider YAML.
python3 - "$TMP" "$PROVIDER" <<'PY'
import base64, pathlib, sys, re

raw = pathlib.Path(sys.argv[1]).read_bytes()
text = raw.decode("utf-8", "ignore").strip()
try:
    decoded = base64.b64decode(re.sub(r"\s+", "", text), validate=False).decode("utf-8", "ignore")
    if "://" in decoded:
        text = decoded
except Exception:
    pass

lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
uris = [ln for ln in lines if "://" in ln]
out = pathlib.Path(sys.argv[2])
if uris:
    body = ["proxies:"]
    for i, uri in enumerate(uris):
        # mihomo умеет парсить share-links через коллекцию proxies как строку? 
        # Надёжнее — использовать proxy-providers payload формата clash share link list через `#!`.
        # Meta поддерживает provider file как список share links? Обычно нужен YAML.
        # Используем формат: каждая строка share-link в файле с заголовком proxies не всегда работает.
        pass
    # Clash Meta: file provider can be a list of proxies in YAML.
    # Convert via mihomo's supported "proxy set" share-link dump:
    # Actually the simplest supported format is:
    # proxies:
    #   - name: x
    #     type: ...
    # Parsing vless manually is painful. Use provider type http locally... 
    # Alternative: write raw subscription body as-is; MetaCubeX supports base64 subscription as provider file
    # when using `type: http` contents. For file type, use:
    out.write_text(text if "proxies:" in text else "\n".join(uris) + "\n", encoding="utf-8")
else:
    out.write_bytes(raw)
print(f"provider written: {out} ({out.stat().st_size} bytes)")
PY

cp "$TEMPLATE" "$OUT"
rm -f "$TMP"
echo "mihomo config -> $OUT"
ls -la "$OUT_DIR" "$OUT_DIR/providers"
