from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class SeenLotsStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(seen_lots)").fetchall()
            }
            if columns and "chat_id" not in columns:
                conn.execute("DROP TABLE seen_lots")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_lots (
                    lot_key TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    buyout_price INTEGER NOT NULL,
                    notified_at TEXT NOT NULL,
                    PRIMARY KEY (lot_key, chat_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_state (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def lot_key(
        item_id: str,
        buyout_price: int,
        start_time: str,
        end_time: str,
        amount: int,
        *,
        quality: int | None = None,
        potential: int | None = None,
    ) -> str:
        payload = (
            f"{item_id}:{buyout_price}:{start_time}:{end_time}:{amount}:"
            f"{quality}:{potential}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def is_seen(self, lot_key: str, chat_id: str) -> bool:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM seen_lots WHERE lot_key = ? AND chat_id = ? LIMIT 1",
                    (lot_key, chat_id),
                ).fetchone()
            return row is not None

    def mark_seen(self, lot_key: str, chat_id: str, item_id: str, buyout_price: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_lots (lot_key, chat_id, item_id, buyout_price, notified_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (lot_key, chat_id, item_id, buyout_price, now),
                )

    def try_claim(self, lot_key: str, chat_id: str, item_id: str, buyout_price: int) -> bool:
        """Атомарно помечает лот для пользователя, если он ещё не был отправлен."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_lots (lot_key, chat_id, item_id, buyout_price, notified_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (lot_key, chat_id, item_id, buyout_price, now),
                )
                return cursor.rowcount > 0

    def clear_seen(self, chat_id: str | None = None) -> int:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                if chat_id is None:
                    cursor = conn.execute("DELETE FROM seen_lots")
                else:
                    cursor = conn.execute(
                        "DELETE FROM seen_lots WHERE chat_id = ?",
                        (chat_id,),
                    )
                return cursor.rowcount

    def unclaim(self, lot_key: str, chat_id: str) -> None:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM seen_lots WHERE lot_key = ? AND chat_id = ?",
                    (lot_key, chat_id),
                )

    def get_scan_cursor(self) -> int:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM scan_state WHERE key = 'cursor' LIMIT 1"
                ).fetchone()
            return int(row[0]) if row else 0

    def set_scan_cursor(self, cursor: int) -> None:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO scan_state (key, value) VALUES ('cursor', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (cursor,),
                )
