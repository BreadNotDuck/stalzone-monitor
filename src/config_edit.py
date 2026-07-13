from __future__ import annotations

from pathlib import Path

import yaml

from .config import _parse_artifact_qualities


def _load_raw(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _save_raw(config_path: Path, raw: dict) -> None:
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)


def get_artifact_qualities(config_path: Path) -> list[int]:
    return list(_parse_artifact_qualities(_load_raw(config_path)))


def toggle_artifact_quality(config_path: Path, quality: int) -> tuple[list[int], bool]:
    """Переключает редкость. Возвращает (новый список, включена ли редкость)."""
    if not 0 <= quality <= 5:
        raise ValueError("Редкость должна быть от 0 до 5")

    raw = _load_raw(config_path)
    enabled = set(_parse_artifact_qualities(raw))

    if quality in enabled:
        if len(enabled) <= 1:
            raise ValueError("Нельзя отключить все редкости")
        enabled.remove(quality)
        is_on = False
    else:
        enabled.add(quality)
        is_on = True

    raw["artifact_qualities"] = sorted(enabled)
    _save_raw(config_path, raw)
    return sorted(enabled), is_on
