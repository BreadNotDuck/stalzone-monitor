#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Мониторинг дешёвых лотов на аукционе STALZONE с уведомлениями в Telegram"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Путь к config.yaml (по умолчанию: config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Выполнить одну проверку и выйти",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Запустить мониторинг без меню",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Консольное меню вместо Telegram-бота",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.once:
        from src.menu import _run_once

        _run_once(args.config)
        return 0

    if args.monitor:
        from src.menu import _start_monitor

        _start_monitor(args.config)
        return 0

    if args.console:
        from src.menu import run_menu

        run_menu(args.config)
        return 0

    try:
        from src.telegram_bot import run_telegram_bot

        run_telegram_bot(args.config)
    except ValueError as exc:
        print(f"Telegram не настроен: {exc}", file=sys.stderr)
        print("Запускаю консольное меню...", file=sys.stderr)
        from src.menu import run_menu

        run_menu(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
