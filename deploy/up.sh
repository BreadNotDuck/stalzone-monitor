#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Создай .env из .env.example и заполни токены."
  exit 1
fi

if [[ ! -f config.yaml ]]; then
  echo "Создай config.yaml из config.yaml.example"
  exit 1
fi

mkdir -p data

docker compose pull --ignore-buildable 2>/dev/null || true
docker compose up -d --build

echo
echo "STALZONE Monitor запущен в фоне."
echo "Логи:    docker compose logs -f"
echo "Стоп:    docker compose down"
echo "Статус:  docker compose ps"
