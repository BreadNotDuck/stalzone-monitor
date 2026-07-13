from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .artifact_meta import DEFAULT_ARTIFACT_POTENTIALS, DEFAULT_ARTIFACT_QUALITIES


@dataclass(frozen=True)
class ItemWatch:
    id: str
    name: str | None = None
    discount_percent: float | None = None


@dataclass(frozen=True)
class Settings:
    region: str
    api_base_url: str
    poll_interval_seconds: int
    lots_limit: int
    artifact_lots_limit: int
    fast_scan: bool
    auto_start_monitor: bool
    default_discount_percent: float
    above_reference_percent: float
    auction_fee_percent: float
    next_lot_reference_percent: float
    request_delay_seconds: float
    api_max_retries: int
    scan_workers: int
    scan_batch_size: int
    watch_artifacts: bool
    artifact_qualities: tuple[int, ...]
    artifact_potentials: tuple[int, ...]
    catalog_realm: str
    custom_items: list[ItemWatch]
    api_token: str | None
    client_id: str | None
    client_secret: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    db_path: Path
    config_path: Path


def _parse_artifact_qualities(raw: dict) -> tuple[int, ...]:
    if "artifact_qualities" in raw:
        values = raw["artifact_qualities"]
        if not isinstance(values, list) or not values:
            raise ValueError("artifact_qualities должен быть непустым списком чисел 0–5")
        return tuple(sorted({int(v) for v in values}))

    if "artifact_quality" in raw:
        return (int(raw["artifact_quality"]),)

    return DEFAULT_ARTIFACT_QUALITIES


def _parse_artifact_potentials(raw: dict) -> tuple[int, ...]:
    if "artifact_potentials" in raw:
        values = raw["artifact_potentials"]
        if not isinstance(values, list) or not values:
            raise ValueError("artifact_potentials должен быть непустым списком (0, 5, 10, 15)")
        return tuple(sorted({int(v) for v in values}))

    return DEFAULT_ARTIFACT_POTENTIALS


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv()

    config_path = config_path or Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            f"Файл конфигурации не найден: {config_path}. "
            "Скопируйте config.yaml.example в config.yaml и заполните его."
        )

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    defaults = raw.get("defaults") or {}
    watch_artifacts = bool(raw.get("watch_artifacts", True))

    custom_items: list[ItemWatch] = []
    for entry in raw.get("custom_items") or raw.get("items") or []:
        custom_items.append(
            ItemWatch(
                id=str(entry["id"]),
                name=entry.get("name"),
                discount_percent=entry.get("discount_percent"),
            )
        )

    if not watch_artifacts and not custom_items:
        raise ValueError(
            "Включите watch_artifacts: true или добавьте предметы через меню / custom_items"
        )

    return Settings(
        region=str(raw.get("region", "RU")).upper(),
        api_base_url=str(raw.get("api_base_url", "https://eapi.stalzone.com")).rstrip("/"),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 120)),
        lots_limit=int(raw.get("lots_limit", 20)),
        artifact_lots_limit=int(raw.get("artifact_lots_limit", 50)),
        fast_scan=bool(raw.get("fast_scan", False)),
        auto_start_monitor=bool(raw.get("auto_start_monitor", True)),
        default_discount_percent=float(defaults.get("discount_percent", 10)),
        above_reference_percent=float(defaults.get("above_reference_percent", 5)),
        auction_fee_percent=float(defaults.get("auction_fee_percent", 6)),
        next_lot_reference_percent=float(defaults.get("next_lot_reference_percent", 1)),
        request_delay_seconds=float(raw.get("request_delay_seconds", 0.15)),
        api_max_retries=int(raw.get("api_max_retries", 5)),
        scan_workers=max(1, int(raw.get("scan_workers", 6))),
        scan_batch_size=max(0, int(raw.get("scan_batch_size", 0))),
        watch_artifacts=watch_artifacts,
        artifact_qualities=_parse_artifact_qualities(raw),
        artifact_potentials=_parse_artifact_potentials(raw),
        catalog_realm=str(raw.get("catalog_realm", "ru")).lower(),
        custom_items=custom_items,
        api_token=os.getenv("STALZONE_API_TOKEN") or None,
        client_id=os.getenv("STALZONE_CLIENT_ID") or None,
        client_secret=os.getenv("STALZONE_CLIENT_SECRET") or None,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        db_path=Path(raw.get("db_path", "data/seen_lots.db")),
        config_path=config_path,
    )
