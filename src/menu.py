from __future__ import annotations

from pathlib import Path

from .catalog import ItemCatalog
from .config import ItemWatch
from .watchlist import (
    add_custom_item,
    load_custom_items,
    remove_custom_item,
)


def run_menu(config_path: Path) -> None:
    catalog = ItemCatalog()

    while True:
        print()
        print("=== STALZONE Monitor ===")
        print("1. Запустить мониторинг")
        print("2. Одна проверка")
        print("3. Добавить предмет")
        print("4. Удалить свой предмет")
        print("5. Список отслеживаемых")
        print("0. Выход")
        choice = input("\nВыбор: ").strip()

        if choice == "1":
            _start_monitor(config_path)
        elif choice == "2":
            _run_once(config_path)
        elif choice == "3":
            _add_item(config_path, catalog)
        elif choice == "4":
            _remove_item(config_path)
        elif choice == "5":
            _show_list(config_path, catalog)
        elif choice == "0":
            print("Пока!")
            return
        else:
            print("Неизвестный пункт меню.")


def _build_monitor(config_path: Path):
    from .api import StalzoneClient
    from .config import load_settings
    from .monitor import AuctionMonitor
    from .notifier import TelegramNotifier
    from .storage import SeenLotsStore

    from .subscriptions import SubscriptionsStore

    settings = load_settings(config_path)
    client = StalzoneClient(
        base_url=settings.api_base_url,
        region=settings.region,
        api_token=settings.api_token,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        request_delay_seconds=settings.request_delay_seconds,
        max_retries=settings.api_max_retries,
        pool_size=settings.scan_workers,
    )
    return AuctionMonitor(
        settings=settings,
        client=client,
        store=SeenLotsStore(settings.db_path),
        notifier=TelegramNotifier(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        ),
        subs_store=SubscriptionsStore(settings.db_path),
    )


def _start_monitor(config_path: Path) -> None:
    try:
        monitor = _build_monitor(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка: {exc}")
        return

    print("\nМониторинг запущен. Ctrl+C для остановки.\n")
    try:
        monitor.run_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")


def _run_once(config_path: Path) -> None:
    try:
        monitor = _build_monitor(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка: {exc}")
        return

    result = monitor.run_once()
    print(f"Готово. {result.summary()}")


def _add_item(config_path: Path, catalog: ItemCatalog) -> None:
    print("\n--- Добавить предмет ---")
    print("1. Поиск по названию")
    print("2. Ввести item id вручную")
    mode = input("Выбор: ").strip()

    item: ItemWatch | None = None

    if mode == "1":
        query = input("Название (часть): ").strip()
        if not query:
            print("Пустой запрос.")
            return
        try:
            results = catalog.search(query, limit=15)
        except Exception as exc:
            print(f"Ошибка поиска: {exc}")
            return

        if not results:
            print("Ничего не найдено.")
            return

        for index, found in enumerate(results, start=1):
            tag = " [артефакт]" if found.category == "artefact" else ""
            print(f"{index}. {found.name} ({found.id}){tag}")

        pick = input("Номер (Enter — отмена): ").strip()
        if not pick.isdigit():
            print("Отменено.")
            return
        idx = int(pick) - 1
        if idx < 0 or idx >= len(results):
            print("Неверный номер.")
            return
        found = results[idx]
        item = ItemWatch(id=found.id, name=found.name)

    elif mode == "2":
        item_id = input("Item id: ").strip()
        if not item_id:
            print("Пустой id.")
            return
        found = catalog.find_by_id(item_id)
        name = found.name if found else None
        item = ItemWatch(id=item_id, name=name)
    else:
        print("Неизвестный режим.")
        return

    if item is None:
        return

    if add_custom_item(config_path, item):
        print(f"Добавлено: {item.name or item.id} ({item.id})")
    else:
        print("Этот предмет уже в списке.")


def _remove_item(config_path: Path) -> None:
    items = load_custom_items(config_path)
    if not items:
        print("\nСвоих предметов нет.")
        return

    print("\n--- Удалить предмет ---")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {item.name or item.id} ({item.id})")

    pick = input("Номер (Enter — отмена): ").strip()
    if not pick.isdigit():
        print("Отменено.")
        return
    idx = int(pick) - 1
    if idx < 0 or idx >= len(items):
        print("Неверный номер.")
        return

    removed = items[idx]
    if remove_custom_item(config_path, removed.id):
        print(f"Удалено: {removed.name or removed.id}")
    else:
        print("Не удалось удалить.")


def _show_list(config_path: Path, catalog: ItemCatalog) -> None:
    print("\n--- Отслеживаемые предметы ---")
    print("• Артефакты: особый/редкий/исключительный/легендарный")
    try:
        count = len(catalog.load_artifacts())
        print(f"  Всего артефактов в базе: {count}")
    except Exception as exc:
        print(f"  Не удалось загрузить каталог: {exc}")

    custom = load_custom_items(config_path)
    print(f"\n• Свои предметы: {len(custom)}")
    if not custom:
        print("  (пусто — добавьте через пункт 3)")
    for item in custom:
        print(f"  - {item.name or item.id} ({item.id})")
