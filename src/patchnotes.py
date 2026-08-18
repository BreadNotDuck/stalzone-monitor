from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchNote:
    version: str
    date: str
    title: str
    highlights: tuple[str, ...]
    details: tuple[str, ...] = ()


# Новые сверху. Добавляй сюда каждую заметную поставку.
PATCH_NOTES: tuple[PatchNote, ...] = (
    PatchNote(
        version="1.9",
        date="18.08.2026",
        title="Рассылка патчноутов",
        highlights=(
            "📬 новый патч приходит в чат всем с активной подпиской",
            "в 📜 Патчноуты можно выключить рассылку: <b>Рассылка патчей: ВЫКЛ</b>",
        ),
        details=(
            "Лоты и патчи — разные переключатели. Выключение лотов не глушит патчи.",
        ),
    ),
    PatchNote(
        version="1.8",
        date="18.08.2026",
        title="Фильтр лотов без медианы",
        highlights=(
            "ℹ️ в <b>📊 Порог</b> можно выключить лоты без медианы",
            "если выкл — приходят только сделки с историей продаж",
        ),
    ),
    PatchNote(
        version="1.7",
        date="17.08.2026",
        title="Баланс и игнор артов",
        highlights=(
            "💰 в <b>📊 Порог</b> можно задать свой баланс — лоты дороже не приходят",
            "🔇 кнопка <b>Игнор</b> в меню: список, добавить, снять",
            "на карточке лота — <b>Не слать этот арт</b>",
        ),
        details=(
            "Баланс 0 / «Без лимита» — фильтр выключен.",
        ),
    ),
    PatchNote(
        version="1.6",
        date="15.08.2026",
        title="Патчноуты в боте",
        highlights=(
            "📜 кнопка <b>Патчноуты</b> в меню",
            "листай версии стрелками прямо в чате",
            "каждое обновление с датой и коротким списком изменений",
        ),
        details=(
            "Новые записи добавляются вверху списка.",
        ),
    ),
    PatchNote(
        version="1.5",
        date="15.08.2026",
        title="Огонёк по двум лотам",
        highlights=(
            "🔥 теперь, если <b>этот и следующий</b> лот ниже медианы",
            "✅ если ниже медианы только текущий лот",
        ),
        details=(
            "Раньше огонёк ставился при скидке 20%+ — теперь он про «двойную» дешевизну.",
        ),
    ),
    PatchNote(
        version="1.4",
        date="14.08.2026",
        title="Умные подписи к медиане",
        highlights=(
            "📐 выше медианы, но ниже порога → «стоимость отличается на +n%»",
            "⚠️ выше порога → предупреждение как раньше",
            "ℹ️ если медианы нет — бот прямо пишет об этом",
        ),
    ),
    PatchNote(
        version="1.3",
        date="13.08.2026",
        title="Новый формат лота и настройки",
        highlights=(
            "📨 лоты в новом читаемом формате с эмодзи",
            "💵 сразу сумма прибыли, без лишнего текста про комиссию",
            "🔕 можно <b>выключить</b> показ лотов выше медианы на порог",
            "✏️ свои значения порогов вручную (%, ₽)",
            "📈 график кнопкой: картинка PNG или текст",
            "📊 в лоте — 7д sparkline с макс/мин",
        ),
        details=(
            "Все пороги только ≥ 0 — убрали кнопки, которые уводили в минус.",
            "Проверка и график больше не клинят меню бота.",
        ),
    ),
    PatchNote(
        version="1.2",
        date="11.08.2026",
        title="График медианы картинкой",
        highlights=(
            "📈 кнопка «Медиана продаж» шлёт PNG-график",
            "линии цен, медиана пунктиром, кириллица в подписях",
        ),
        details=(
            "Починен rate-limit API: бот больше не падает на «timestamp too large».",
        ),
    ),
    PatchNote(
        version="1.1",
        date="11.08.2026",
        title="Пороги, подписка по часам, sparkline",
        highlights=(
            "📊 порог мин. прибыли % и ₽",
            "👥 подписку можно двигать по часам и дням",
            "📊 маленький unicode-график прямо в тексте лота",
        ),
    ),
    PatchNote(
        version="1.0",
        date="2026",
        title="Старт монитора",
        highlights=(
            "🔍 сканер дешёвых лотов STALZONE",
            "📦 категории: артефакты, ядра, оружие, броня, контейнеры",
            "🔔 личные уведомления и подписки",
        ),
    ),
)


def latest_patch_version() -> str | None:
    return PATCH_NOTES[0].version if PATCH_NOTES else None


def patch_count() -> int:
    return len(PATCH_NOTES)


def get_patch(index: int) -> PatchNote | None:
    if not PATCH_NOTES:
        return None
    idx = max(0, min(index, len(PATCH_NOTES) - 1))
    return PATCH_NOTES[idx]


def format_patch_note(index: int = 0) -> str:
    note = get_patch(index)
    if note is None:
        return "📜 Пока нет записей в патчноутах."

    total = len(PATCH_NOTES)
    lines = [
        f"📜 <b>Патчноут {escape(note.version)}</b>",
        f"📅 {escape(note.date)} · <i>{escape(note.title)}</i>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "",
    ]
    for item in note.highlights:
        lines.append(f"• {item}")
    if note.details:
        lines.append("")
        lines.append("<b>Ещё</b>")
        for item in note.details:
            lines.append(f"· {item}")
    lines.extend(
        [
            "",
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
            f"<i>{index + 1} / {total}</i> · листать кнопками ниже",
        ]
    )
    return "\n".join(lines)


def format_patch_broadcast(index: int = 0) -> str:
    note = get_patch(index)
    if note is None:
        return "📜 Пока нет записей в патчноутах."
    lines = [
        "✨ <b>Новое обновление</b>",
        f"📜 Патчноут <b>{escape(note.version)}</b> · {escape(note.date)}",
        f"<i>{escape(note.title)}</i>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        "",
    ]
    for item in note.highlights:
        lines.append(f"• {item}")
    if note.details:
        lines.append("")
        for item in note.details:
            lines.append(f"· {item}")
    lines.extend(
        [
            "",
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
            "Полный список — кнопка <b>📜 Патчноуты</b>.",
            "Рассылку можно выключить там же.",
        ]
    )
    return "\n".join(lines)


def patch_keyboard(index: int = 0, *, notify: bool = True) -> dict[str, Any]:
    total = len(PATCH_NOTES)
    if total <= 0:
        return {"inline_keyboard": []}

    idx = max(0, min(index, total - 1))
    row: list[dict[str, str]] = []
    if idx < total - 1:
        row.append({"text": "◀️ Старее", "callback_data": f"patch:{idx + 1}"})
    row.append({"text": f"{idx + 1}/{total}", "callback_data": "patch:noop"})
    if idx > 0:
        row.append({"text": "Новее ▶️", "callback_data": f"patch:{idx - 1}"})

    extra: list[list[dict[str, str]]] = [row]
    if idx != 0:
        extra.append([{"text": "🔝 К свежему", "callback_data": "patch:0"}])
    extra.append(
        [
            {
                "text": (
                    "📢 Рассылка патчей: ВКЛ"
                    if notify
                    else "🔕 Рассылка патчей: ВЫКЛ"
                ),
                "callback_data": f"patch:notify:{idx}",
            }
        ]
    )
    return {"inline_keyboard": extra}


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
