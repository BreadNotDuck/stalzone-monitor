from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from .artifact_meta import (
    ALL_ARTIFACT_QUALITIES,
    potential_label,
    potential_labels,
    quality_emoji,
    quality_label,
    quality_labels,
)
from .catalog import CatalogItem, ItemCatalog
from .charts import format_history_chart
from .config import ItemWatch, load_settings
from .menu import _build_monitor
from .notifier import escape_html
from .subscriptions import QUALITY_LOT_CATEGORIES, SIMPLE_LOT_CATEGORIES, SubscriptionsStore
from .watchlist import add_custom_item, load_custom_items, remove_custom_item

BTN_START = "▶️ Старт"
BTN_STOP = "⏹ Стоп"
BTN_ONCE = "🔍 Проверка"
BTN_STATUS = "📋 Статус"
BTN_RESET = "🔄 Сброс памяти"
BTN_LOTS = "📦 Лоты"
BTN_THRESHOLD = "📊 Порог"
BTN_ADD = "➕ Добавить"
BTN_REMOVE = "➖ Удалить"
BTN_SUBS = "👥 Подписки"
BTN_NOTIFY_ON = "🔔 Уведомления: вкл"
BTN_NOTIFY_OFF = "🔕 Уведомления: выкл"

USER_MENU_BUTTONS_STATIC = [
    [BTN_ONCE, BTN_STATUS],
    [BTN_LOTS, BTN_THRESHOLD],
    [BTN_RESET],
]

ADMIN_MENU_BUTTONS_STATIC = [
    [BTN_START, BTN_STOP],
    [BTN_ONCE, BTN_STATUS],
    [BTN_LOTS, BTN_THRESHOLD],
    [BTN_RESET],
    [BTN_ADD, BTN_REMOVE],
    [BTN_SUBS],
]

LOT_CATEGORY_LABELS = {
    "artifacts": "🧿 Артефакты",
    "module_cores": "⚙️ Ядра модулей",
    "weapons": "🔫 Мастерское оружие",
    "armor": "🛡 Мастерская броня",
    "containers": "📦 Мастерские контейнеры",
}

LOT_NAV_BUTTONS = {
    "artifacts": "Артефакты — редкости",
    "module_cores": "Ядра модулей — редкости",
}


@dataclass
class ChatState:
    mode: str | None = None
    search_results: list[CatalogItem] = field(default_factory=list)


class TelegramBotApp:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        settings = load_settings(config_path)
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")

        self.token = settings.telegram_bot_token
        self.admin_chat_id = str(settings.telegram_chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.catalog = ItemCatalog(realm=settings.catalog_realm)
        self.subs = SubscriptionsStore(settings.db_path)
        self.offset = 0
        self.states: dict[str, ChatState] = {}
        self.monitor_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.notifier = _build_monitor(config_path).notifier

    def run(self) -> None:
        print("Telegram-бот запущен. Управление через меню в чате.")
        self._ensure_telegram_reachable()
        settings = load_settings(self.config_path)
        self._send_menu(
            self.admin_chat_id,
            "Бот готов.\n"
            "▶️ <b>Старт</b> — запустить мониторинг\n"
            "🔍 <b>Проверка</b> — одна проверка с отчётом\n"
            "📦 <b>Лоты</b> — категории и редкости: артефакты, ядра модулей, оружие, броня, контейнеры\n"
            "🔔 <b>Уведомления</b> — вкл/выкл личные сообщения от бота\n"
            "👥 <b>Подписки</b> — выдать или забрать доступ пользователям\n"
            "🔄 <b>Сброс памяти</b> — если лоты не приходят повторно",
            admin=True,
        )
        if settings.auto_start_monitor:
            time.sleep(1)
            self._start_monitor(self.admin_chat_id)

        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self.offset = update["update_id"] + 1
                    self._handle_update(update)
            except requests.RequestException as exc:
                print(f"[BOT] ошибка polling: {exc}")
                time.sleep(3)

    def _ensure_telegram_reachable(self) -> None:
        """Падаем сразу, если api.telegram.org недоступен или токен битый."""
        try:
            response = requests.get(
                f"{self.base_url}/getMe",
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise SystemExit(
                f"Telegram API недоступен с этой машины: {exc}. "
                "Добавь рабочий HTTPS_PROXY в .env / секрет ENV_FILE."
            ) from exc

        if not payload.get("ok"):
            raise SystemExit(f"Telegram getMe failed: {payload}")
        username = payload.get("result", {}).get("username", "?")
        print(f"[BOT] Telegram OK (@{username})")

    def _get_updates(self) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.base_url}/getUpdates",
            params={"offset": self.offset, "timeout": 30},
            timeout=(15, 65),
        )
        response.raise_for_status()
        return response.json().get("result", [])

    def _handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message["chat"]["id"])
        text = (message.get("text") or "").strip()
        if not text:
            return

        subscriber = self._register_from_message(message)
        is_admin = self._is_admin(chat_id)

        if text == "/start":
            self._state(chat_id).mode = None
            if is_admin:
                self._send_menu(chat_id, "Меню STALZONE Monitor:", admin=True)
            elif subscriber.is_active:
                self._send_menu(chat_id, f"Привет! Подписка активна {subscriber.status_label()}.")
            else:
                self._send(
                    chat_id,
                    "⛔ <b>Подписка не активна.</b>\n"
                    f"Статус: {escape_html(subscriber.status_label())}\n"
                    "Обратись к администратору для получения доступа.",
                )
            return

        if not is_admin and not subscriber.is_active:
            self._send(
                chat_id,
                "⛔ Нет активной подписки.\n"
                f"Статус: {escape_html(subscriber.status_label())}",
            )
            return

        state = self._state(chat_id)
        if state.mode == "add":
            if not is_admin:
                state.mode = None
                self._send(chat_id, "Добавление предметов доступно только администратору.")
                return
            self._handle_add_query(chat_id, text)
            return
        if state.mode == "remove":
            if not is_admin:
                state.mode = None
                self._send(chat_id, "Удаление предметов доступно только администратору.")
                return
            self._handle_remove_pick(chat_id, text)
            return
        if state.mode == "admin_add_user" and is_admin:
            self._handle_admin_add_user(chat_id, text)
            return

        handlers = {
            BTN_START: self._start_monitor,
            BTN_STOP: self._stop_monitor,
            BTN_ONCE: self._run_once,
            BTN_STATUS: self._show_list,
            BTN_RESET: self._reset_seen,
            BTN_LOTS: self._show_lots,
            BTN_THRESHOLD: self._show_threshold,
            BTN_ADD: self._begin_add,
            BTN_REMOVE: self._begin_remove,
            BTN_SUBS: self._show_subscriptions,
            BTN_NOTIFY_ON: self._toggle_notifications,
            BTN_NOTIFY_OFF: self._toggle_notifications,
            "🚀 Мониторинг": self._start_monitor,
            "📋 Список": self._show_list,
        }
        handler = handlers.get(text)
        if handler:
            if text in {BTN_START, BTN_STOP, BTN_SUBS, BTN_ADD, BTN_REMOVE} and not is_admin:
                self._send(chat_id, "Эта функция доступна только администратору.")
                return
            handler(chat_id)
        else:
            self._send_menu(chat_id, "Используй кнопки меню 👇", admin=is_admin)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        chat_id = str(callback["message"]["chat"]["id"])
        data = callback.get("data", "")
        callback_id = callback["id"]
        message_id = callback["message"]["message_id"]

        if data.startswith("ulot:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            action = data[5:]
            if action == "artifacts":
                self._answer_callback(callback_id, "Артефакты")
                self._edit_artifacts_panel(chat_id, message_id)
                return
            if action == "module_cores":
                self._answer_callback(callback_id, "Ядра модулей")
                self._edit_module_cores_panel(chat_id, message_id)
                return
            if action == "back":
                self._answer_callback(callback_id, "Лоты")
                self._edit_lots_keyboard(chat_id, message_id)
                return
            if action not in SIMPLE_LOT_CATEGORIES:
                self._answer_callback(callback_id, "Неизвестная категория")
                return
            try:
                _, is_on = self.subs.toggle_lot_category(chat_id, action)
                label = LOT_CATEGORY_LABELS[action]
                state = "включено" if is_on else "выключено"
                self._answer_callback(callback_id, f"{label}: {state}")
                self._edit_lots_keyboard(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("ucoreqlt:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            quality = int(data[9:])
            try:
                _, is_on = self.subs.toggle_core_quality(chat_id, quality)
                state = "включена" if is_on else "выключена"
                self._answer_callback(callback_id, f"{quality_label(quality)}: {state}")
                if self._callback_is_module_cores_panel(callback):
                    self._edit_module_cores_panel(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("uqlt:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            quality = int(data[5:])
            try:
                _, is_on = self.subs.toggle_quality(chat_id, quality)
                state = "включена" if is_on else "выключена"
                self._answer_callback(callback_id, f"{quality_label(quality)}: {state}")
                if self._callback_is_artifacts_panel(callback):
                    self._edit_artifacts_panel(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("uthr:"):
            if data == "uthr:noop":
                self._answer_callback(callback_id, "Выбери значение ниже")
                return
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            action = data[5:]
            try:
                if action.startswith("set:"):
                    value = self.subs.set_above_reference_percent(chat_id, float(action[4:]))
                else:
                    value = self.subs.adjust_above_reference_percent(chat_id, float(action))
                self._answer_callback(callback_id, f"⚠️ порог: {value:g}%")
                self._edit_threshold_keyboard(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("upft:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            action = data[5:]
            try:
                if action.startswith("set:"):
                    value = self.subs.set_min_profit_percent(chat_id, float(action[4:]))
                else:
                    value = self.subs.adjust_min_profit_percent(chat_id, float(action))
                self._answer_callback(callback_id, f"Мин %: {value:g}")
                self._edit_threshold_keyboard(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("upfa:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            action = data[5:]
            try:
                if action.startswith("set:"):
                    value = self.subs.set_min_profit_amount(chat_id, int(float(action[4:])))
                else:
                    value = self.subs.adjust_min_profit_amount(chat_id, int(float(action)))
                self._answer_callback(callback_id, f"Мин ₽: {value:,}".replace(",", " "))
                self._edit_threshold_keyboard(chat_id, message_id)
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data.startswith("hist:"):
            if not self._is_admin(chat_id):
                subscriber = self.subs.get(chat_id)
                if subscriber is None or not subscriber.is_active:
                    self._answer_callback(callback_id, "Нет активной подписки")
                    return
            # hist:{item_id}:{q}:{p}
            parts = data.split(":")
            if len(parts) < 4:
                self._answer_callback(callback_id, "Битые данные")
                return
            item_id = parts[1]
            quality = int(parts[2])
            potential = int(parts[3])
            q = None if quality < 0 else quality
            p = None if potential < 0 else potential
            self._answer_callback(callback_id, "Строю график…")
            self._send_history_chart(chat_id, item_id, quality=q, potential=p)
            return

        if not self._is_admin(chat_id):
            self._answer_callback(callback_id, "Только для администратора")
            return

        if data.startswith("subpick:"):
            user_id = data[8:]
            self._answer_callback(callback_id, "Ок")
            self._edit_subscription_panel(chat_id, message_id, user_id)
            return

        if data.startswith("subadj:"):
            # subadj:{chat_id}:{key}  key = +7, -7, +30, ...
            parts = data.split(":", 2)
            if len(parts) != 3:
                return
            user_id, key = parts[1], parts[2]
            try:
                subscriber = self.subs.adjust_key(user_id, key)
                self._answer_callback(callback_id, subscriber.status_label())
                self._edit_subscription_panel(chat_id, message_id, user_id)
                if subscriber.is_active:
                    self._send(
                        user_id,
                        f"✅ Подписка обновлена: {escape_html(subscriber.status_label())}",
                    )
                elif key == "zero":
                    self._send(user_id, "❌ Подписка снята.")
            except ValueError as exc:
                self._answer_callback(callback_id, str(exc))
            return

        if data == "subadd":
            self._state(chat_id).mode = "admin_add_user"
            self._answer_callback(callback_id, "Жду chat_id")
            self._send(chat_id, "Отправь <b>chat_id</b> пользователя (число).")
            return

        if data.startswith("add:"):
            item_id = data[4:]
            found = self.catalog.find_by_id(item_id)
            item = ItemWatch(id=item_id, name=found.name if found else None)
            if add_custom_item(self.config_path, item):
                text = f"✅ Добавлено: {escape_html(item.name or item.id)} (<code>{item_id}</code>)"
            else:
                text = "ℹ️ Уже в списке."
            self._state(chat_id).mode = None
            self._answer_callback(callback_id, "Готово")
            self._send_menu(chat_id, text)
            return

        if data.startswith("del:"):
            item_id = data[4:]
            if remove_custom_item(self.config_path, item_id):
                text = f"🗑 Удалено: <code>{item_id}</code>"
            else:
                text = "Не найдено в списке."
            self._state(chat_id).mode = None
            self._answer_callback(callback_id, "Готово")
            self._send_menu(chat_id, text)

    def _is_admin(self, chat_id: str) -> bool:
        return chat_id == self.admin_chat_id

    def _register_from_message(self, message: dict[str, Any]):
        chat = message["chat"]
        user = message.get("from") or {}
        chat_id = str(chat["id"])
        username = user.get("username")
        display_name = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        ) or None
        is_new = self.subs.get(chat_id) is None
        subscriber = self.subs.upsert_user(
            chat_id,
            username=username,
            display_name=display_name,
        )
        if is_new and not self._is_admin(chat_id):
            label = f"@{username}" if username else (display_name or chat_id)
            self._send(
                self.admin_chat_id,
                f"👤 Новый пользователь: {escape_html(label)} (<code>{chat_id}</code>)",
            )
        return subscriber

    def _handle_admin_add_user(self, chat_id: str, text: str) -> None:
        self._state(chat_id).mode = None
        user_id = text.strip()
        if not user_id.isdigit():
            self._send_menu(chat_id, "Нужен числовой chat_id.", admin=True)
            return
        subscriber = self.subs.upsert_user(user_id)
        self._send_menu(
            chat_id,
            f"✅ Пользователь добавлен: <code>{user_id}</code>\n"
            f"Статус: {escape_html(subscriber.status_label())}",
            admin=True,
        )
        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": self._subscription_panel_text(subscriber),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._subscription_adjust_keyboard(user_id)},
        })

    def _subscription_panel_text(self, subscriber) -> str:
        mark = "✅" if subscriber.is_active else "❌"
        return (
            f"<b>{mark} {escape_html(self.subs.display_name(subscriber))}</b>\n"
            f"<code>{subscriber.chat_id}</code>\n"
            f"Статус: {escape_html(subscriber.status_label())}\n\n"
            "Изменить подписку:"
        )

    def _subscription_adjust_keyboard(self, user_id: str) -> list[list[dict[str, str]]]:
        return [
            [
                {"text": "+1ч", "callback_data": f"subadj:{user_id}:+1h"},
                {"text": "−1ч", "callback_data": f"subadj:{user_id}:-1h"},
                {"text": "+6ч", "callback_data": f"subadj:{user_id}:+6h"},
                {"text": "−6ч", "callback_data": f"subadj:{user_id}:-6h"},
            ],
            [
                {"text": "+12ч", "callback_data": f"subadj:{user_id}:+12h"},
                {"text": "−12ч", "callback_data": f"subadj:{user_id}:-12h"},
                {"text": "+1д", "callback_data": f"subadj:{user_id}:+1"},
                {"text": "−1д", "callback_data": f"subadj:{user_id}:-1"},
            ],
            [
                {"text": "+1 нед", "callback_data": f"subadj:{user_id}:+7"},
                {"text": "−1 нед", "callback_data": f"subadj:{user_id}:-7"},
                {"text": "+1 мес", "callback_data": f"subadj:{user_id}:+30"},
                {"text": "−1 мес", "callback_data": f"subadj:{user_id}:-30"},
            ],
            [
                {"text": "+3 мес", "callback_data": f"subadj:{user_id}:+90"},
                {"text": "−3 мес", "callback_data": f"subadj:{user_id}:-90"},
                {"text": "🗑 Обнулить", "callback_data": f"subadj:{user_id}:zero"},
            ],
        ]

    def _subscriptions_list_text(self) -> str:
        subscribers = self.subs.list_all()
        if not subscribers:
            return (
                "<b>👥 Подписчики</b>\n"
                "Пока никого нет. Новые появятся после /start или кнопки «Добавить»."
            )
        lines = ["<b>👥 Подписчики</b>", "Выбери пользователя:"]
        for sub in subscribers[:20]:
            mark = "✅" if sub.is_active else "❌"
            lines.append(
                f"{mark} {escape_html(self.subs.display_name(sub))} — "
                f"{escape_html(sub.status_label())}"
            )
        if len(subscribers) > 20:
            lines.append(f"... и ещё {len(subscribers) - 20}")
        return "\n".join(lines)

    def _subscriptions_list_keyboard(self) -> list[list[dict[str, str]]]:
        keyboard: list[list[dict[str, str]]] = []
        for sub in self.subs.list_all()[:20]:
            mark = "✅" if sub.is_active else "❌"
            label = f"{mark} {self.subs.display_name(sub)}"[:60]
            keyboard.append([{"text": label, "callback_data": f"subpick:{sub.chat_id}"}])
        keyboard.append([{"text": "➕ Добавить по chat_id", "callback_data": "subadd"}])
        return keyboard

    def _show_subscriptions(self, chat_id: str) -> None:
        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": self._subscriptions_list_text(),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._subscriptions_list_keyboard()},
        })

    def _edit_subscription_panel(self, chat_id: str, message_id: int, user_id: str) -> None:
        subscriber = self.subs.get(user_id)
        if subscriber is None:
            self._api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "Пользователь не найден.",
            })
            return
        self._api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._subscription_panel_text(subscriber),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._subscription_adjust_keyboard(user_id)},
        })

    def _start_monitor(self, chat_id: str) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            self._send(chat_id, "Мониторинг уже запущен.")
            return

        self.stop_event.clear()

        def worker() -> None:
            try:
                monitor = _build_monitor(self.config_path)
                monitor.run_forever(self.stop_event)
            except Exception as exc:
                self._send(chat_id, f"❌ Ошибка мониторинга: {escape_html(str(exc))}")
            finally:
                self._send(chat_id, "⏹ Мониторинг остановлен.")

        self.monitor_thread = threading.Thread(target=worker, daemon=True)
        self.monitor_thread.start()
        settings = load_settings(self.config_path)
        potentials = potential_labels(list(settings.artifact_potentials))
        self._send(
            chat_id,
            f"🚀 Мониторинг запущен.\n"
            f"Регион: {settings.region}, интервал: {settings.poll_interval_seconds} сек.\n"
            f"Сканируются все редкости, заточки {potentials}.\n"
            f"Свои фильтры — в 📦 Лоты.\n"
            f"Уведомление: ≥10% ниже следующего лота (медиана — только справка).",
        )

    def _stop_monitor(self, chat_id: str) -> None:
        if not self.monitor_thread or not self.monitor_thread.is_alive():
            self._send(chat_id, "Мониторинг не запущен.")
            return
        self.stop_event.set()
        self._send(chat_id, "Останавливаю после текущего цикла...")

    def _run_once(self, chat_id: str) -> None:
        self._send(chat_id, "🔍 Запускаю проверку...")
        try:
            monitor = _build_monitor(self.config_path)
            result = monitor.run_once()
            hint = ""
            if result.notified == 0 and result.candidates > 0 and result.skipped_seen > 0:
                hint = "\n\n💡 Есть кандидаты, но все уже были отправлены. Нажми 🔄 Сброс памяти."
            elif result.notified == 0 and result.with_lots == 0:
                hint = "\n\n💡 Нет лотов нужной редкости/заточки на аукционе."
            elif result.notified == 0 and result.candidates == 0:
                hint = "\n\n💡 Нет лотов на ≥10% дешевле следующего."
            self._send_menu(chat_id, f"✅ {result.summary()}{hint}")
        except Exception as exc:
            self._send_menu(chat_id, f"❌ Ошибка: {escape_html(str(exc))}")

    def _notify_button(self, chat_id: str) -> str:
        if self.subs.is_notifications_enabled(chat_id):
            return BTN_NOTIFY_ON
        return BTN_NOTIFY_OFF

    def _menu_keyboard(self, chat_id: str, *, admin: bool) -> list[list[str]]:
        notify_row = [self._notify_button(chat_id)]
        if admin:
            keyboard = [row[:] for row in ADMIN_MENU_BUTTONS_STATIC]
            keyboard.insert(2, notify_row)
            return keyboard
        keyboard = [row[:] for row in USER_MENU_BUTTONS_STATIC]
        keyboard.insert(2, notify_row)
        return keyboard

    def _toggle_notifications(self, chat_id: str) -> None:
        self.subs.upsert_user(chat_id)
        is_on = self.subs.toggle_notifications(chat_id)
        state = "включены" if is_on else "выключены"
        self._send_menu(
            chat_id,
            f"{'🔔' if is_on else '🔕'} Личные уведомления <b>{state}</b>.",
            admin=self._is_admin(chat_id),
        )

    @staticmethod
    def _callback_is_artifacts_panel(callback: dict[str, Any]) -> bool:
        keyboard = callback.get("message", {}).get("reply_markup", {}).get("inline_keyboard", [])
        return any(
            button.get("callback_data", "").startswith("uqlt:")
            for row in keyboard
            for button in row
        )

    @staticmethod
    def _callback_is_module_cores_panel(callback: dict[str, Any]) -> bool:
        keyboard = callback.get("message", {}).get("reply_markup", {}).get("inline_keyboard", [])
        return any(
            button.get("callback_data", "").startswith("ucoreqlt:")
            for row in keyboard
            for button in row
        )

    def _enabled_qualities_summary(self, user_chat_id: str, *, cores: bool = False) -> str:
        if cores:
            enabled = self.subs.get_enabled_core_qualities(user_chat_id)
        else:
            enabled = self.subs.get_enabled_qualities(user_chat_id)
        if not enabled:
            return "выкл."
        return escape_html(quality_labels(list(enabled)))

    def _lots_text(self, user_chat_id: str) -> str:
        enabled = self.subs.get_lot_categories(user_chat_id)
        lines = [
            "<b>Какие лоты присылать</b>",
            "Бот сканирует всё — здесь выбираешь категории для себя:",
            "",
            "🧿 Артефакты — кнопка ниже",
            "⚙️ Ядра модулей — кнопка ниже",
        ]
        for key in SIMPLE_LOT_CATEGORIES:
            mark = "✅" if enabled[key] else "⬜"
            lines.append(f"{mark} {LOT_CATEGORY_LABELS[key]}")
        lines.append("\nОружие, броня и контейнеры — нажми, чтобы включить или выключить.")
        return "\n".join(lines)

    def _lots_keyboard(self, user_chat_id: str) -> list[list[dict[str, str]]]:
        enabled = self.subs.get_lot_categories(user_chat_id)
        keyboard: list[list[dict[str, str]]] = []
        for key in QUALITY_LOT_CATEGORIES:
            keyboard.append([{
                "text": LOT_NAV_BUTTONS[key],
                "callback_data": f"ulot:{key}",
            }])
        for key in SIMPLE_LOT_CATEGORIES:
            mark = "✅" if enabled[key] else "⬜"
            label = f"{mark} {LOT_CATEGORY_LABELS[key]}"[:60]
            keyboard.append([{"text": label, "callback_data": f"ulot:{key}"}])
        return keyboard

    def _show_lots(self, chat_id: str) -> None:
        self.subs.upsert_user(chat_id)
        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": self._lots_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._lots_keyboard(chat_id)},
        })

    def _edit_lots_keyboard(self, chat_id: str, message_id: int) -> None:
        self._api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._lots_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._lots_keyboard(chat_id)},
        })

    def _artifacts_panel_text(self, user_chat_id: str) -> str:
        qualities = self._enabled_qualities_summary(user_chat_id)
        return (
            "<b>🧿 Артефакты — редкости</b>\n"
            f"Сейчас: {qualities}\n\n"
            "Нажми редкость, чтобы включить или выключить.\n"
            "⚪ Обычный и 🟢 Необычный — выключены по умолчанию."
        )

    def _artifacts_panel_keyboard(self, user_chat_id: str) -> list[list[dict[str, str]]]:
        keyboard = self._qualities_keyboard(user_chat_id, callback_prefix="uqlt:")
        keyboard.append([{"text": "◀️ Назад к лотам", "callback_data": "ulot:back"}])
        return keyboard

    def _module_cores_panel_text(self, user_chat_id: str) -> str:
        qualities = self._enabled_qualities_summary(user_chat_id, cores=True)
        return (
            "<b>⚙️ Ядра модулей — редкости</b>\n"
            f"Сейчас: {qualities}\n\n"
            "Нажми редкость, чтобы включить или выключить.\n"
            "⚪ Обычный и 🟢 Необычный — выключены по умолчанию."
        )

    def _module_cores_panel_keyboard(self, user_chat_id: str) -> list[list[dict[str, str]]]:
        keyboard = self._qualities_keyboard(user_chat_id, callback_prefix="ucoreqlt:")
        keyboard.append([{"text": "◀️ Назад к лотам", "callback_data": "ulot:back"}])
        return keyboard

    def _edit_module_cores_panel(self, chat_id: str, message_id: int) -> None:
        self._api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._module_cores_panel_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._module_cores_panel_keyboard(chat_id)},
        })

    def _edit_artifacts_panel(self, chat_id: str, message_id: int) -> None:
        self._api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._artifacts_panel_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._artifacts_panel_keyboard(chat_id)},
        })

    def _qualities_keyboard(
        self,
        user_chat_id: str,
        *,
        callback_prefix: str = "uqlt:",
        qualities: tuple[int, ...] | None = None,
    ) -> list[list[dict[str, str]]]:
        if qualities is None:
            if callback_prefix == "ucoreqlt:":
                qualities = self.subs.get_enabled_core_qualities(user_chat_id)
            else:
                qualities = self.subs.get_enabled_qualities(user_chat_id)
        enabled = set(qualities)
        keyboard: list[list[dict[str, str]]] = []
        row: list[dict[str, str]] = []
        for quality in ALL_ARTIFACT_QUALITIES:
            mark = "✅" if quality in enabled else "⬜"
            name = quality_label(quality)
            if quality in (0, 1) and quality not in enabled:
                name = f"{name} (выкл.)"
            label = f"{mark} {quality_emoji(quality)} {name}"[:60]
            row.append({"text": label, "callback_data": f"{callback_prefix}{quality}"})
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        return keyboard

    def _threshold_text(self, user_chat_id: str) -> str:
        warn = self.subs.get_above_reference_percent(user_chat_id)
        min_pct = self.subs.get_min_profit_percent(user_chat_id)
        min_sum = self.subs.get_min_profit_amount(user_chat_id)
        warn_l = f"{warn:g}".replace(".", ",")
        pct_l = f"{min_pct:g}".replace(".", ",")
        return (
            "<b>📊 Пороги уведомлений</b>\n\n"
            f"<b>1) Мин. прибыль %</b> (к след. лоту): <b>{pct_l}%</b>\n"
            "Лот придёт, только если дешевле следующего минимум на этот %.\n\n"
            f"<b>2) Мин. прибыль ₽</b> (после комиссии): <b>{min_sum:,} ₽</b>\n".replace(",", " ")
            + "Лот придёт, только если «выгода» ≥ этой суммы.\n\n"
            f"<b>3) Предупреждение ⚠️</b>: от <b>+{warn_l}%</b> дороже медианы.\n"
            "Нажми блок ниже, чтобы менять значения."
        )

    def _threshold_keyboard(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "— Мин. прибыль % —", "callback_data": "uthr:noop"}],
            [
                {"text": "−5%", "callback_data": "upft:-5"},
                {"text": "−1%", "callback_data": "upft:-1"},
                {"text": "+1%", "callback_data": "upft:1"},
                {"text": "+5%", "callback_data": "upft:5"},
            ],
            [
                {"text": "5%", "callback_data": "upft:set:5"},
                {"text": "10%", "callback_data": "upft:set:10"},
                {"text": "15%", "callback_data": "upft:set:15"},
                {"text": "20%", "callback_data": "upft:set:20"},
            ],
            [{"text": "— Мин. прибыль ₽ —", "callback_data": "uthr:noop"}],
            [
                {"text": "−10к", "callback_data": "upfa:-10000"},
                {"text": "−1к", "callback_data": "upfa:-1000"},
                {"text": "+1к", "callback_data": "upfa:1000"},
                {"text": "+10к", "callback_data": "upfa:10000"},
            ],
            [
                {"text": "0", "callback_data": "upfa:set:0"},
                {"text": "5к", "callback_data": "upfa:set:5000"},
                {"text": "25к", "callback_data": "upfa:set:25000"},
                {"text": "100к", "callback_data": "upfa:set:100000"},
            ],
            [{"text": "— ⚠️ Дороже ориентира —", "callback_data": "uthr:noop"}],
            [
                {"text": "−5%", "callback_data": "uthr:-5"},
                {"text": "−1%", "callback_data": "uthr:-1"},
                {"text": "+1%", "callback_data": "uthr:1"},
                {"text": "+5%", "callback_data": "uthr:5"},
            ],
            [
                {"text": "3%", "callback_data": "uthr:set:3"},
                {"text": "5%", "callback_data": "uthr:set:5"},
                {"text": "10%", "callback_data": "uthr:set:10"},
                {"text": "15%", "callback_data": "uthr:set:15"},
            ],
        ]

    def _show_threshold(self, chat_id: str) -> None:
        self.subs.upsert_user(chat_id)
        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": self._threshold_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._threshold_keyboard()},
        })

    def _edit_threshold_keyboard(self, chat_id: str, message_id: int) -> None:
        self._api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": self._threshold_text(chat_id),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": self._threshold_keyboard()},
        })

    def _send_history_chart(
        self,
        chat_id: str,
        item_id: str,
        *,
        quality: int | None,
        potential: int | None,
    ) -> None:
        try:
            monitor = _build_monitor(self.config_path)
            history = monitor.client.get_price_history(item_id, limit=100, with_additional=True)
            entries = []
            for entry in history:
                if entry.price <= 0:
                    continue
                if quality is not None and entry.quality != quality:
                    continue
                if potential is not None and entry.potential != potential:
                    continue
                entries.append(entry)
            # История обычно приходит от новых к старым — для графика нужна хронология
            entries = list(reversed(entries))
            prices = [e.price for e in entries]
            times = [e.time for e in entries]
            found = self.catalog.find_by_id(item_id)
            name = found.name if found else item_id
            median = None
            if len(prices) >= 3:
                import statistics

                median = int(statistics.median(prices))
            elif prices:
                median = int(sum(prices) / len(prices))
            text = format_history_chart(
                item_name=name,
                prices=prices,
                times=times,
                median=median,
                quality_label=quality_label(quality) if quality is not None else None,
                potential_label=potential_label(potential) if potential is not None else None,
            )
            self._api("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
        except Exception as exc:
            self._send(chat_id, f"❌ Не удалось построить график: {escape_html(str(exc))}")

    def _reset_seen(self, chat_id: str) -> None:
        try:
            monitor = _build_monitor(self.config_path)
            scope = None if self._is_admin(chat_id) else chat_id
            cleared = monitor.store.clear_seen(scope)
            label = "вся память" if scope is None else "твоя память"
            self._send_menu(
                chat_id,
                f"🔄 Сброшена {label} ({cleared} записей). Нажми 🔍 Проверка.",
                admin=self._is_admin(chat_id),
            )
        except Exception as exc:
            self._send_menu(chat_id, f"❌ Ошибка: {escape_html(str(exc))}")

    def _show_list(self, chat_id: str) -> None:
        try:
            artifact_count = len(self.catalog.load_artifacts())
            core_count = len(self.catalog.load_module_cores())
            weapon_count = len(self.catalog.load_master_weapons())
            armor_count = len(self.catalog.load_master_armor())
            container_count = len(self.catalog.load_master_containers())
        except Exception as exc:
            artifact_count = f"ошибка ({exc})"
            core_count = weapon_count = armor_count = container_count = "—"

        settings = load_settings(self.config_path)
        potentials = potential_labels(list(settings.artifact_potentials))
        my_qualities = quality_labels(list(self.subs.get_enabled_qualities(chat_id)))
        my_core_qualities = quality_labels(list(self.subs.get_enabled_core_qualities(chat_id)))
        threshold = self.subs.get_above_reference_percent(chat_id)
        threshold_label = f"{threshold:g}".replace(".", ",")
        min_pct = self.subs.get_min_profit_percent(chat_id)
        min_pct_label = f"{min_pct:g}".replace(".", ",")
        min_sum = self.subs.get_min_profit_amount(chat_id)
        lot_prefs = self.subs.get_lot_categories(chat_id)
        notify_on = self.subs.is_notifications_enabled(chat_id)
        lot_lines = []
        art_qualities = self.subs.get_enabled_qualities(chat_id)
        core_qualities = self.subs.get_enabled_core_qualities(chat_id)
        lot_lines.append(
            f"  {LOT_CATEGORY_LABELS['artifacts']}"
            + (f" — {my_qualities}" if art_qualities else " — выкл.")
        )
        lot_lines.append(
            f"  {LOT_CATEGORY_LABELS['module_cores']}"
            + (f" — {my_core_qualities}" if core_qualities else " — выкл.")
        )
        for key in SIMPLE_LOT_CATEGORIES:
            mark = "✅" if lot_prefs[key] else "⬜"
            lot_lines.append(f"  {mark} {LOT_CATEGORY_LABELS[key]}")

        custom = load_custom_items(self.config_path)
        is_admin = self._is_admin(chat_id)
        lines = [
            "<b>Отслеживаемые предметы</b>",
            f"• Артефакты: {artifact_count} шт., сканируются все редкости",
            f"• Ядра модулей: {core_count} шт., сканируются все редкости",
            f"• Мастерское оружие: {weapon_count} шт.",
            f"• Мастерская броня: {armor_count} шт.",
            f"• Мастерские контейнеры: {container_count} шт.",
            f"<b>Личные уведомления:</b> {'🔔 вкл' if notify_on else '🔕 выкл'}",
            "<b>Твои категории (📦 Лоты):</b>",
            *lot_lines,
            f"  Мин. прибыль: {min_pct_label}% / {min_sum:,} ₽".replace(",", " "),
            f"  Порог «дороже ориентира»: +{threshold_label}%",
            f"  Заточки: {potentials}",
            "  Уведомление: ≥10% ниже следующего лота",
            "  Медиана продаж — только справка в сообщении",
        ]
        if is_admin:
            lines.append(f"• Свои предметы: {len(custom)}")
            if custom:
                for item in custom:
                    lines.append(
                        f"  — {escape_html(item.name or item.id)} (<code>{item.id}</code>)"
                    )
            else:
                lines.append("  (пусто — нажми ➕ Добавить)")

        self._send_menu(chat_id, "\n".join(lines))

    def _begin_add(self, chat_id: str) -> None:
        self._state(chat_id).mode = "add"
        self._send(
            chat_id,
            "Отправь <b>название</b> для поиска или <b>item id</b> (например <code>y3k2j</code>).",
        )

    def _handle_add_query(self, chat_id: str, text: str) -> None:
        self._state(chat_id).mode = None

        if len(text) <= 8 and text.isalnum():
            found = self.catalog.find_by_id(text)
            item = ItemWatch(id=text, name=found.name if found else None)
            if add_custom_item(self.config_path, item):
                self._send_menu(chat_id, f"✅ Добавлено: {escape_html(item.name or item.id)}")
            else:
                self._send_menu(chat_id, "ℹ️ Уже в списке.")
            return

        try:
            results = self.catalog.search(text, limit=8)
        except Exception as exc:
            self._send_menu(chat_id, f"❌ Ошибка поиска: {escape_html(str(exc))}")
            return

        if not results:
            self._send_menu(chat_id, "Ничего не найдено.")
            return

        keyboard = []
        for found in results:
            tag = " 🧿" if found.category == "artefact" else ""
            label = f"{found.name} ({found.id}){tag}"[:60]
            keyboard.append([{"text": label, "callback_data": f"add:{found.id}"}])

        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": f"Найдено {len(results)}. Нажми чтобы добавить:",
            "reply_markup": {"inline_keyboard": keyboard},
        })

    def _begin_remove(self, chat_id: str) -> None:
        items = load_custom_items(self.config_path)
        if not items:
            self._send_menu(chat_id, "Своих предметов нет.")
            return

        keyboard = []
        for item in items:
            label = f"🗑 {item.name or item.id}"[:60]
            keyboard.append([{"text": label, "callback_data": f"del:{item.id}"}])

        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": "Выбери предмет для удаления:",
            "reply_markup": {"inline_keyboard": keyboard},
        })

    def _handle_remove_pick(self, chat_id: str, text: str) -> None:
        self._state(chat_id).mode = None
        self._send_menu(chat_id, "Используй кнопки под сообщением для удаления.")

    def _state(self, chat_id: str) -> ChatState:
        if chat_id not in self.states:
            self.states[chat_id] = ChatState()
        return self.states[chat_id]

    def _send_menu(self, chat_id: str, text: str, *, admin: bool | None = None) -> None:
        if admin is None:
            admin = self._is_admin(chat_id)
        keyboard = self._menu_keyboard(chat_id, admin=admin)
        self._api("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "keyboard": keyboard,
                "resize_keyboard": True,
                "is_persistent": True,
            },
        })

    def _send(self, chat_id: str, text: str) -> None:
        self.notifier.send(text, chat_id=chat_id)

    def _answer_callback(self, callback_id: str, text: str) -> None:
        self._api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def _api(self, method: str, payload: dict[str, Any]) -> None:
        try:
            response = requests.post(
                f"{self.base_url}/{method}",
                json=payload,
                timeout=(15, 60),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[BOT] {method} failed: {exc}")


def run_telegram_bot(config_path: Path) -> None:
    TelegramBotApp(config_path).run()
