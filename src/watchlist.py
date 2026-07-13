from __future__ import annotations

from pathlib import Path

import yaml

from .config import ItemWatch


def load_custom_items(config_path: Path) -> list[ItemWatch]:
    if not config_path.exists():
        return []

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    items: list[ItemWatch] = []
    for entry in raw.get("custom_items") or raw.get("items") or []:
        items.append(
            ItemWatch(
                id=str(entry["id"]),
                name=entry.get("name"),
                discount_percent=entry.get("discount_percent"),
            )
        )
    return items


def save_custom_items(config_path: Path, items: list[ItemWatch]) -> None:
    if config_path.exists():
        with config_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    else:
        raw = {}

    raw["custom_items"] = [
        {
            "id": item.id,
            "name": item.name,
        }
        for item in items
    ]
    if "items" in raw:
        del raw["items"]

    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)


def add_custom_item(config_path: Path, item: ItemWatch) -> bool:
    items = load_custom_items(config_path)
    if any(existing.id == item.id for existing in items):
        return False
    items.append(item)
    save_custom_items(config_path, items)
    return True


def remove_custom_item(config_path: Path, item_id: str) -> bool:
    items = load_custom_items(config_path)
    filtered = [item for item in items if item.id != item_id]
    if len(filtered) == len(items):
        return False
    save_custom_items(config_path, filtered)
    return True
