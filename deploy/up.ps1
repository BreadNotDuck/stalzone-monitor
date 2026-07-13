$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Error "Создай .env из .env.example и заполни токены."
}

if (-not (Test-Path "config.yaml")) {
    Write-Error "Создай config.yaml из config.yaml.example"
}

New-Item -ItemType Directory -Force -Path "data" | Out-Null

docker compose up -d --build

Write-Host ""
Write-Host "STALZONE Monitor запущен в Docker."
Write-Host "Логи:    docker compose logs -f"
Write-Host "Стоп:    docker compose down"
