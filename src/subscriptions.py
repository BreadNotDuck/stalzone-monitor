from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .artifact_meta import ALL_ARTIFACT_QUALITIES, DEFAULT_ARTIFACT_QUALITIES

DEFAULT_ABOVE_REFERENCE_PERCENT = 5.0
DEFAULT_MIN_PROFIT_PERCENT = 10.0
DEFAULT_MIN_PROFIT_AMOUNT = 0

LOT_CATEGORIES = ("artifacts", "module_cores", "weapons", "armor", "containers")
QUALITY_LOT_CATEGORIES = ("artifacts", "module_cores")
SIMPLE_LOT_CATEGORIES = ("weapons", "armor", "containers")
DEFAULT_LOT_CATEGORIES = {
    "artifacts": True,
    "module_cores": False,
    "weapons": False,
    "armor": False,
    "containers": False,
}


@dataclass(frozen=True)
class Subscriber:
    chat_id: str
    username: str | None
    display_name: str | None
    expires_at: datetime | None
    created_at: datetime

    @property
    def is_active(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at > datetime.now(timezone.utc)

    def status_label(self) -> str:
        if self.expires_at is None:
            return "нет подписки"
        if self.is_active:
            return f"до {self.expires_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
        return f"истекла {self.expires_at.astimezone().strftime('%d.%m.%Y %H:%M')}"


# key -> (days, hours)
ADJUSTMENTS: dict[str, tuple[int, int]] = {
    "+1h": (0, 1),
    "-1h": (0, -1),
    "+6h": (0, 6),
    "-6h": (0, -6),
    "+12h": (0, 12),
    "-12h": (0, -12),
    "+1": (1, 0),
    "-1": (-1, 0),
    "+7": (7, 0),
    "-7": (-7, 0),
    "+30": (30, 0),
    "-30": (-30, 0),
    "+90": (90, 0),
    "-90": (-90, 0),
}


class SubscriptionsStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id TEXT PRIMARY KEY,
                    username TEXT,
                    display_name TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    enabled_qualities TEXT
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(subscribers)").fetchall()
            }
            if "enabled_qualities" not in columns:
                conn.execute("ALTER TABLE subscribers ADD COLUMN enabled_qualities TEXT")
            if "above_reference_percent" not in columns:
                conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN above_reference_percent REAL"
                )
            for column in ("watch_artifacts", "watch_weapons", "watch_armor", "watch_containers"):
                if column not in columns:
                    default = 1 if column == "watch_artifacts" else 0
                    conn.execute(
                        f"ALTER TABLE subscribers ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}"
                    )
            if "notifications_enabled" not in columns:
                conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN notifications_enabled INTEGER NOT NULL DEFAULT 1"
                )
            if "watch_module_cores" not in columns:
                conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN watch_module_cores INTEGER NOT NULL DEFAULT 0"
                )
            if "enabled_core_qualities" not in columns:
                conn.execute("ALTER TABLE subscribers ADD COLUMN enabled_core_qualities TEXT")
            if "min_profit_percent" not in columns:
                conn.execute("ALTER TABLE subscribers ADD COLUMN min_profit_percent REAL")
            if "min_profit_amount" not in columns:
                conn.execute("ALTER TABLE subscribers ADD COLUMN min_profit_amount INTEGER")
            if "show_above_median" not in columns:
                conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN show_above_median INTEGER NOT NULL DEFAULT 1"
                )
            if "chart_mode" not in columns:
                conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN chart_mode TEXT NOT NULL DEFAULT 'png'"
                )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _format_dt(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _parse_qualities(raw: str | None) -> tuple[int, ...]:
        if not raw:
            return DEFAULT_ARTIFACT_QUALITIES
        return tuple(sorted({int(part) for part in raw.split(",") if part.strip()}))

    @staticmethod
    def _format_qualities(qualities: tuple[int, ...]) -> str:
        return ",".join(str(q) for q in sorted(qualities))

    def get_enabled_qualities(self, chat_id: str) -> tuple[int, ...]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT enabled_qualities FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or not row[0]:
            return DEFAULT_ARTIFACT_QUALITIES
        parsed = self._parse_qualities(row[0])
        return parsed or DEFAULT_ARTIFACT_QUALITIES

    def toggle_quality(self, chat_id: str, quality: int) -> tuple[tuple[int, ...], bool]:
        if quality not in ALL_ARTIFACT_QUALITIES:
            raise ValueError("Редкость должна быть от 0 до 5")

        self.upsert_user(chat_id)
        enabled = set(self.get_enabled_qualities(chat_id))
        if quality in enabled:
            enabled.remove(quality)
            is_on = False
        else:
            enabled.add(quality)
            is_on = True

        new_qualities = tuple(sorted(enabled))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET enabled_qualities = ? WHERE chat_id = ?",
                    (self._format_qualities(new_qualities), chat_id),
                )
        return new_qualities, is_on

    def get_enabled_core_qualities(self, chat_id: str) -> tuple[int, ...]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT enabled_core_qualities FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or not row[0]:
            return DEFAULT_ARTIFACT_QUALITIES
        parsed = self._parse_qualities(row[0])
        return parsed or DEFAULT_ARTIFACT_QUALITIES

    def toggle_core_quality(self, chat_id: str, quality: int) -> tuple[tuple[int, ...], bool]:
        if quality not in ALL_ARTIFACT_QUALITIES:
            raise ValueError("Редкость должна быть от 0 до 5")

        self.upsert_user(chat_id)
        enabled = set(self.get_enabled_core_qualities(chat_id))
        if quality in enabled:
            enabled.remove(quality)
            is_on = False
        else:
            enabled.add(quality)
            is_on = True

        new_qualities = tuple(sorted(enabled))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET enabled_core_qualities = ? WHERE chat_id = ?",
                    (self._format_qualities(new_qualities), chat_id),
                )
        return new_qualities, is_on

    def get_above_reference_percent(
        self, chat_id: str, default: float = DEFAULT_ABOVE_REFERENCE_PERCENT
    ) -> float:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT above_reference_percent FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or row[0] is None:
            return default
        return float(row[0])

    def set_above_reference_percent(self, chat_id: str, value: float) -> float:
        self.upsert_user(chat_id)
        clamped = max(0.0, min(50.0, float(value)))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET above_reference_percent = ? WHERE chat_id = ?",
                    (clamped, chat_id),
                )
        return clamped

    def adjust_above_reference_percent(self, chat_id: str, delta: float) -> float:
        current = self.get_above_reference_percent(chat_id)
        return self.set_above_reference_percent(chat_id, current + delta)

    def get_min_profit_percent(
        self, chat_id: str, default: float = DEFAULT_MIN_PROFIT_PERCENT
    ) -> float:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT min_profit_percent FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or row[0] is None:
            return default
        return float(row[0])

    def set_min_profit_percent(self, chat_id: str, value: float) -> float:
        self.upsert_user(chat_id)
        clamped = max(0.0, min(80.0, float(value)))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET min_profit_percent = ? WHERE chat_id = ?",
                    (clamped, chat_id),
                )
        return clamped

    def adjust_min_profit_percent(self, chat_id: str, delta: float) -> float:
        return self.set_min_profit_percent(chat_id, self.get_min_profit_percent(chat_id) + delta)

    def get_min_profit_amount(
        self, chat_id: str, default: int = DEFAULT_MIN_PROFIT_AMOUNT
    ) -> int:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT min_profit_amount FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or row[0] is None:
            return default
        return int(row[0])

    def set_min_profit_amount(self, chat_id: str, value: int) -> int:
        self.upsert_user(chat_id)
        clamped = max(0, min(50_000_000, int(value)))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET min_profit_amount = ? WHERE chat_id = ?",
                    (clamped, chat_id),
                )
        return clamped

    def adjust_min_profit_amount(self, chat_id: str, delta: int) -> int:
        return self.set_min_profit_amount(chat_id, self.get_min_profit_amount(chat_id) + delta)

    def get_show_above_median(self, chat_id: str, default: bool = True) -> bool:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT show_above_median FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or row[0] is None:
            return default
        return bool(row[0])

    def set_show_above_median(self, chat_id: str, enabled: bool) -> bool:
        self.upsert_user(chat_id)
        value = 1 if enabled else 0
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET show_above_median = ? WHERE chat_id = ?",
                    (value, chat_id),
                )
        return bool(value)

    def toggle_show_above_median(self, chat_id: str) -> bool:
        return self.set_show_above_median(chat_id, not self.get_show_above_median(chat_id))

    def get_chart_mode(self, chat_id: str, default: str = "png") -> str:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT chart_mode FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row or not row[0]:
            return default
        mode = str(row[0]).strip().lower()
        return mode if mode in {"png", "text"} else default

    def set_chart_mode(self, chat_id: str, mode: str) -> str:
        self.upsert_user(chat_id)
        normalized = "text" if str(mode).strip().lower() == "text" else "png"
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET chart_mode = ? WHERE chat_id = ?",
                    (normalized, chat_id),
                )
        return normalized

    def get_lot_categories(self, chat_id: str) -> dict[str, bool]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT watch_artifacts, watch_module_cores, watch_weapons,
                           watch_armor, watch_containers
                    FROM subscribers WHERE chat_id = ?
                    """,
                    (chat_id,),
                ).fetchone()
        if not row:
            return dict(DEFAULT_LOT_CATEGORIES)
        return {
            "artifacts": bool(row[0]),
            "module_cores": bool(row[1]),
            "weapons": bool(row[2]),
            "armor": bool(row[3]),
            "containers": bool(row[4]),
        }

    def toggle_lot_category(self, chat_id: str, category: str) -> tuple[dict[str, bool], bool]:
        if category not in LOT_CATEGORIES:
            raise ValueError("Неизвестная категория лотов")

        self.upsert_user(chat_id)
        current = self.get_lot_categories(chat_id)
        enabled_count = sum(1 for value in current.values() if value)
        is_on = not current[category]
        if not is_on and enabled_count <= 1:
            raise ValueError("Нельзя отключить все категории лотов")

        column = {
            "artifacts": "watch_artifacts",
            "module_cores": "watch_module_cores",
            "weapons": "watch_weapons",
            "armor": "watch_armor",
            "containers": "watch_containers",
        }[category]
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    f"UPDATE subscribers SET {column} = ? WHERE chat_id = ?",
                    (1 if is_on else 0, chat_id),
                )
        current[category] = is_on
        return current, is_on

    def wants_lot_category(self, chat_id: str, category: str) -> bool:
        return self.get_lot_categories(chat_id).get(category, False)

    def is_notifications_enabled(self, chat_id: str) -> bool:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT notifications_enabled FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        if not row:
            return True
        return bool(row[0])

    def toggle_notifications(self, chat_id: str) -> bool:
        self.upsert_user(chat_id)
        is_on = not self.is_notifications_enabled(chat_id)
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET notifications_enabled = ? WHERE chat_id = ?",
                    (1 if is_on else 0, chat_id),
                )
        return is_on

    def receives_notifications(self, chat_id: str) -> bool:
        return self.is_notifications_enabled(chat_id)

    def _row_to_subscriber(self, row: tuple) -> Subscriber:
        return Subscriber(
            chat_id=str(row[0]),
            username=row[1],
            display_name=row[2],
            expires_at=self._parse_dt(row[3]),
            created_at=self._parse_dt(row[4]) or datetime.now(timezone.utc),
        )

    def upsert_user(
        self,
        chat_id: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
    ) -> Subscriber:
        now = datetime.now(timezone.utc)
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                existing = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE subscribers
                        SET username = COALESCE(?, username),
                            display_name = COALESCE(?, display_name)
                        WHERE chat_id = ?
                        """,
                        (username, display_name, chat_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO subscribers (
                            chat_id, username, display_name, expires_at, created_at,
                            enabled_qualities, enabled_core_qualities, above_reference_percent,
                            min_profit_percent, min_profit_amount,
                            watch_artifacts, watch_module_cores, watch_weapons, watch_armor,
                            watch_containers, notifications_enabled
                        )
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chat_id,
                            username,
                            display_name,
                            self._format_dt(now),
                            self._format_qualities(DEFAULT_ARTIFACT_QUALITIES),
                            self._format_qualities(DEFAULT_ARTIFACT_QUALITIES),
                            DEFAULT_ABOVE_REFERENCE_PERCENT,
                            DEFAULT_MIN_PROFIT_PERCENT,
                            DEFAULT_MIN_PROFIT_AMOUNT,
                            1,
                            0,
                            0,
                            0,
                            0,
                            1,
                        ),
                    )
                row = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        return self._row_to_subscriber(row)

    def get(self, chat_id: str) -> Subscriber | None:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        return self._row_to_subscriber(row) if row else None

    def list_all(self) -> list[Subscriber]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_subscriber(row) for row in rows]

    def active_chat_ids(self) -> list[str]:
        now = self._format_dt(datetime.now(timezone.utc))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT chat_id FROM subscribers WHERE expires_at IS NOT NULL AND expires_at > ?",
                    (now,),
                ).fetchall()
        return [str(row[0]) for row in rows]

    def adjust(self, chat_id: str, days: int = 0, hours: int = 0) -> Subscriber:
        subscriber = self.get(chat_id)
        if subscriber is None:
            raise ValueError("Пользователь не найден")

        now = datetime.now(timezone.utc)
        base = subscriber.expires_at if subscriber.expires_at and subscriber.expires_at > now else now
        new_expires = base + timedelta(days=days, hours=hours)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET expires_at = ? WHERE chat_id = ?",
                    (self._format_dt(new_expires), chat_id),
                )
                row = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        return self._row_to_subscriber(row)

    def clear_subscription(self, chat_id: str) -> Subscriber:
        subscriber = self.get(chat_id)
        if subscriber is None:
            raise ValueError("Пользователь не найден")
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE subscribers SET expires_at = NULL WHERE chat_id = ?",
                    (chat_id,),
                )
                row = conn.execute(
                    "SELECT chat_id, username, display_name, expires_at, created_at "
                    "FROM subscribers WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
        return self._row_to_subscriber(row)

    def adjust_key(self, chat_id: str, key: str) -> Subscriber:
        if key == "zero":
            return self.clear_subscription(chat_id)
        if key not in ADJUSTMENTS:
            raise ValueError(f"Неизвестный период: {key}")
        days, hours = ADJUSTMENTS[key]
        return self.adjust(chat_id, days=days, hours=hours)

    def display_name(self, subscriber: Subscriber) -> str:
        if subscriber.username:
            return f"@{subscriber.username}"
        if subscriber.display_name:
            return subscriber.display_name
        return subscriber.chat_id
