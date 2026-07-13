from __future__ import annotations

from typing import Any

# 6 редкостей артефактов (qlt: 0–5)
QUALITY_NAMES: dict[int, str] = {
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
}

# Заточка / потенциал артефакта (ptn)
POTENTIAL_LEVELS: tuple[int, ...] = (0, 5, 10, 15)
DEFAULT_ARTIFACT_POTENTIALS: tuple[int, ...] = (0, 15)


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_quality(additional: dict[str, Any] | None) -> int | None:
    if not additional:
        return None
    for key in ("qlt", "quality", "Quality"):
        value = parse_int(additional.get(key))
        if value is not None and 0 <= value <= 5:
            return value
    return None


def parse_potential(additional: dict[str, Any] | None) -> int | None:
    if not additional:
        return None
    for key in ("ptn", "potential", "Potential"):
        value = parse_int(additional.get(key))
        if value is not None and 0 <= value <= 15:
            return value
    return None


def quality_label(quality: int | None) -> str:
    if quality is None:
        return "неизвестно"
    return QUALITY_NAMES.get(quality, str(quality))


QUALITY_EMOJI: dict[int, str] = {
    0: "⚪",
    1: "🟢",
    2: "🔵",  # особый
    3: "🟣",  # редкий
    4: "🔴",  # исключительный
    5: "🟨",  # легендарный
}


def quality_emoji(quality: int | None) -> str:
    if quality is None:
        return "⚪"
    return QUALITY_EMOJI.get(quality, "⚪")


def quality_labels(qualities: list[int]) -> str:
    if not qualities:
        return "не указано"
    return ", ".join(quality_label(q) for q in sorted(qualities))


# По умолчанию: особый, редкий, исключительный, легендарный
# Обычный (0) и необычный (1) — доступны в меню, но выключены
ALL_ARTIFACT_QUALITIES: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
DEFAULT_ARTIFACT_QUALITIES: tuple[int, ...] = (2, 3, 4, 5)
DEFAULT_OFF_ARTIFACT_QUALITIES: tuple[int, ...] = (0, 1)


def potential_label(potential: int | None) -> str:
    if potential is None:
        return "неизвестно"
    return f"+{potential}"


def potential_labels(potentials: list[int]) -> str:
    if not potentials:
        return "не указано"
    return ", ".join(potential_label(p) for p in sorted(potentials))


def variant_label(quality: int | None, potential: int | None) -> str:
    return f"{quality_label(quality)}, заточка {potential_label(potential)}"
