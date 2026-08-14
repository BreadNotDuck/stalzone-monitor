from __future__ import annotations

import io
from datetime import datetime
from typing import Any


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


def format_history_caption(
    *,
    item_name: str,
    prices: list[int],
    median: int | None = None,
    quality_label: str | None = None,
    potential_label: str | None = None,
) -> str:
    """Короткая подпись к картинке графика."""
    lines: list[str] = [f"<b>{item_name}</b>"]
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
    lines.append(
        f"мин {_money(min(prices))} · макс {_money(max(prices))} · "
        f"посл. {_money(prices[-1])}"
    )
    return "\n".join(lines)


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


def render_history_chart_png(
    *,
    item_name: str,
    prices: list[int],
    times: list[str] | None = None,
    median: int | None = None,
    quality_label: str | None = None,
    potential_label: str | None = None,
) -> bytes:
    """Красивый PNG-график истории продаж для Telegram."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # DejaVu поддерживает кириллицу (ставим fonts-dejavu в Docker).
    for candidate in ("DejaVu Sans", "DejaVu Sans Mono", "Arial Unicode MS", "Segoe UI"):
        try:
            font_manager.findfont(candidate, fallback_to_default=False)
            plt.rcParams["font.family"] = candidate
            break
        except Exception:
            continue

    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=140 if len(prices) > 60 else 160)
    fig.patch.set_facecolor("#0f1419")
    ax.set_facecolor("#151b22")

    subtitle_bits = [b for b in (quality_label, potential_label) if b]
    title = item_name if not subtitle_bits else f"{item_name}  ·  {' · '.join(subtitle_bits)}"

    if not prices:
        ax.text(
            0.5,
            0.5,
            "Нет данных продаж",
            ha="center",
            va="center",
            color="#9aa4b2",
            fontsize=16,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        # слишком плотные маркеры на длинной серии раздувают PNG
        marker_size = 3.0 if len(prices) > 60 else 4.5
        xs: list[Any]
        use_dates = False
        parsed_times = [_parse_time(t) for t in (times or [])]
        if times and len(parsed_times) == len(prices) and all(parsed_times):
            # naive UTC — меньше сюрпризов у matplotlib date converters
            xs = [dt.replace(tzinfo=None) if dt.tzinfo else dt for dt in parsed_times]  # type: ignore[union-attr]
            use_dates = True
        else:
            xs = list(range(1, len(prices) + 1))

        med = median if median is not None else sorted(prices)[len(prices) // 2]
        try:
            if use_dates:
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
                ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
                fig.autofmt_xdate(rotation=25, ha="right")
            ax.fill_between(xs, prices, med, where=[p >= med for p in prices], color="#3d9a6a", alpha=0.18, interpolate=True)
            ax.fill_between(xs, prices, med, where=[p < med for p in prices], color="#c45c5c", alpha=0.18, interpolate=True)
            ax.plot(
                xs,
                prices,
                color="#6cb6ff",
                linewidth=2.2,
                marker="o",
                markersize=marker_size,
                markerfacecolor="#dceeff",
                markeredgewidth=0,
            )
        except (OverflowError, ValueError):
            # fallback: индекс по оси X, если даты/локатор ломаются
            xs = list(range(1, len(prices) + 1))
            ax.cla()
            ax.set_facecolor("#151b22")
            ax.fill_between(xs, prices, med, where=[p >= med for p in prices], color="#3d9a6a", alpha=0.18, interpolate=True)
            ax.fill_between(xs, prices, med, where=[p < med for p in prices], color="#c45c5c", alpha=0.18, interpolate=True)
            ax.plot(
                xs,
                prices,
                color="#6cb6ff",
                linewidth=2.2,
                marker="o",
                markersize=marker_size,
                markerfacecolor="#dceeff",
                markeredgewidth=0,
            )

        ax.axhline(med, color="#f0c14b", linewidth=1.8, linestyle="--", label=f"Медиана {_money(int(med))} ₽")

        ax.set_ylabel("Цена, ₽", color="#c5ced9")
        ax.tick_params(colors="#9aa4b2")
        ax.grid(True, color="#2a3440", linewidth=0.8, alpha=0.9)
        for spine in ax.spines.values():
            spine.set_color("#2a3440")
        ax.legend(loc="upper left", frameon=False, labelcolor="#e8eef5")
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _pos: f"{int(v):,}".replace(",", " "))
        )

    ax.set_title(title, color="#e8eef5", fontsize=15, pad=14, loc="left", fontweight="bold")
    fig.text(
        0.99,
        0.02,
        "stalzone-monitor",
        ha="right",
        va="bottom",
        color="#5b6775",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.02, 0.04, 0.98, 0.96))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return buf.getvalue()
