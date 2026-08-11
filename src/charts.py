from __future__ import annotations

from datetime import datetime


SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int | float], *, width: int = 24) -> str:
    """Компактный unicode-график для текста Telegram."""
    if not values:
        return "—"
    series = list(values[-width:])
    lo = min(series)
    hi = max(series)
    if hi <= lo:
        return SPARK_BLOCKS[-1] * len(series)
    span = hi - lo
    out: list[str] = []
    for value in series:
        idx = int(round((value - lo) / span * (len(SPARK_BLOCKS) - 1)))
        out.append(SPARK_BLOCKS[max(0, min(len(SPARK_BLOCKS) - 1, idx))])
    return "".join(out)


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


def format_history_chart(
    *,
    item_name: str,
    prices: list[int],
    times: list[str] | None = None,
    median: int | None = None,
    quality_label: str | None = None,
    potential_label: str | None = None,
) -> str:
    """Текстовый график продаж + медиана."""
    lines: list[str] = ["📈 <b>Медиана продаж</b>", f"<b>{item_name}</b>"]
    meta: list[str] = []
    if quality_label:
        meta.append(quality_label)
    if potential_label:
        meta.append(potential_label)
    if meta:
        lines.append(" · ".join(meta))

    if not prices:
        lines.append("Нет подходящих продаж в истории.")
        return "\n".join(lines)

    med = median if median is not None else sorted(prices)[len(prices) // 2]
    lines.append(f"Медиана: <b>{_money(int(med))}</b> ₽ · продаж: {len(prices)}")
    lines.append(f"<code>{sparkline(prices)}</code>")
    lines.append(
        f"мин {_money(min(prices))} · макс {_money(max(prices))} · "
        f"посл. {_money(prices[-1])}"
    )

    # Последние точки с «столбиками»
    sample_n = min(12, len(prices))
    sample_prices = prices[-sample_n:]
    sample_times = (times or [""] * len(prices))[-sample_n:]
    lo = min(sample_prices)
    hi = max(sample_prices)
    span = max(1, hi - lo)
    lines.append("")
    lines.append("<pre>")
    for price, raw_t in zip(sample_prices, sample_times, strict=False):
        bar_len = 1 + int(round((price - lo) / span * 14))
        bar = "█" * bar_len
        dt = _parse_time(raw_t)
        stamp = dt.strftime("%d.%m %H:%M") if dt else "—"
        lines.append(f"{stamp} {_money(price):>9} {bar}")
    lines.append("</pre>")
    return "\n".join(lines)
