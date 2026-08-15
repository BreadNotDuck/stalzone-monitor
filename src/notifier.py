from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .charts import sparkline


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> bool:
        target = chat_id or self.chat_id
        if not self.bot_token or not target:
            print(f"[DEV TELEGRAM]\n{text}")
            return True

        payload: dict[str, Any] = {
            "chat_id": target,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        for attempt in range(3):
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json=payload,
                    timeout=(15, 60),
                )
                response.raise_for_status()
                return True
            except requests.RequestException as exc:
                print(f"[TELEGRAM] попытка {attempt + 1}/3: {exc}")
                time.sleep(2 * (attempt + 1))
        return False


def _money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _parse_time(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _week_prices(prices: list[int], times: list[str] | None) -> list[int]:
    if not prices:
        return []
    if not times or len(times) != len(prices):
        return prices[-24:]
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent: list[int] = []
    for price, raw_t in zip(prices, times):
        dt = _parse_time(raw_t)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            recent.append(price)
    return recent or prices[-24:]


def format_deal_message(
    *,
    item_name: str,
    item_id: str,
    buyout_price: int,
    amount: int,
    average_price: int | None,
    reference_count: int | None = None,
    next_lot_price: int | None,
    discount_percent: float,
    end_time: str,
    reason: str,
    quality: int | None = None,
    potential: int | None = None,
    confidence: str = "preliminary",
    auction_fee_percent: float = 6,
    next_lot_reference_percent: float = 1,
    above_reference_percent: float = 5,
    history_prices: list[int] | None = None,
    history_times: list[str] | None = None,
) -> str:
    from .artifact_meta import potential_label, quality_emoji, quality_label

    lines: list[str] = []
    confirmed = confidence == "confirmed"
    ref_gen = "медианы" if confirmed else "ориентира"

    if average_price is not None and average_price > 0:
        sales = f" из {reference_count} продаж" if reference_count else ""
        if buyout_price > average_price:
            markup = (buyout_price / average_price - 1) * 100
            if markup >= above_reference_percent:
                lines.append(
                    f"⚠️ <b>Выше {ref_gen} на {markup:.0f}%</b> "
                    f"({_money(average_price)} ₽{sales})"
                )
            else:
                lines.append(
                    f"📐 Стоимость отличается на <b>+{markup:.0f}%</b> "
                    f"от {ref_gen} ({_money(average_price)} ₽{sales})"
                )
        else:
            discount_vs_median = (1 - buyout_price / average_price) * 100
            next_also_below = (
                next_lot_price is not None and next_lot_price < average_price
            )
            mark = "🔥" if next_also_below else "✅"
            lines.append(
                f"{mark} <b>Ниже {ref_gen} на {discount_vs_median:.0f}%</b> "
                f"({_money(average_price)} ₽{sales})"
            )
    else:
        lines.append("ℹ️ <b>Нет медианы</b> — мало или нет подходящих продаж")

    if next_lot_price is not None:
        next_minus_fee = int(round(next_lot_price * (1 - auction_fee_percent / 100)))
        next_minus_one = int(round(next_lot_price * (1 - next_lot_reference_percent / 100)))
        gap = next_minus_fee - buyout_price
        gap_sign = "+" if gap > 0 else ""
        ref_l = f"{next_lot_reference_percent:g}".replace(".", ",")
        lines.append(
            f"💵 <b>{gap_sign}{_money(gap)}</b> ₽ · "
            f"выставить за <b>{_money(next_minus_one)}</b> ₽ (след. −{ref_l}%)"
        )

    if quality is not None:
        variant = html.escape(quality_label(quality))
        if potential is not None:
            variant += f" — {html.escape(potential_label(potential))}"
        lines.append(f"{quality_emoji(quality)} <b>{variant}</b>")

    lines.append(f"<b>{html.escape(item_name)}</b>")

    price_bits = [f"💰 <b>{_money(buyout_price)}</b> ₽"]
    if next_lot_price is not None:
        next_bit = f"след. <b>{_money(next_lot_price)}</b> ₽"
        if average_price is not None and average_price > 0:
            next_vs_median = (next_lot_price / average_price - 1) * 100
            next_bit += f" ({next_vs_median:+.0f}% от {ref_gen})"
        price_bits.append(next_bit)
    lines.append(" — ".join(price_bits))

    if next_lot_price is not None and next_lot_price > 0:
        discount_vs_next = (1 - buyout_price / next_lot_price) * 100
        lines.append(f"📉 <b>−{discount_vs_next:.0f}%</b> к след. лоту")

    if amount > 1:
        lines.append(f"📦 ×{amount}")

    week = _week_prices(list(history_prices or []), history_times)
    if len(week) >= 2:
        lines.append(
            f"📊 7д <code>{sparkline(week)}</code> "
            f"макс {_money(max(week))} · мин {_money(min(week))}"
        )

    return "\n".join(lines)


def escape_html(text: str) -> str:
    return html.escape(text)


def deal_history_keyboard(
    *,
    item_id: str,
    quality: int | None,
    potential: int | None,
) -> dict[str, Any]:
    q = quality if quality is not None else -1
    p = potential if potential is not None else -1
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📈 Медиана продаж",
                    "callback_data": f"hist:{item_id}:{q}:{p}",
                }
            ]
        ]
    }
