from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

LISTING_URLS = {
    "ru": "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/ru/listing.json",
    "global": "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/global/listing.json",
}


MASTER_RANK = "RANK_MASTER"


@dataclass(frozen=True)
class CatalogItem:
    id: str
    name: str
    category: str
    subcategory: str = ""
    is_master: bool = False


class ItemCatalog:
    def __init__(
        self,
        *,
        realm: str = "ru",
        cache_path: Path | None = None,
        cache_ttl_seconds: int = 86400,
    ) -> None:
        self.realm = realm.lower()
        self.cache_path = cache_path or Path("data/item_catalog.json")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_version = 4

    def load_items(self) -> list[CatalogItem]:
        return self._load_listing()

    def load_artifacts(self) -> list[CatalogItem]:
        return [item for item in self._load_listing() if item.category == "artefact"]

    def load_master_weapons(self) -> list[CatalogItem]:
        return [
            item
            for item in self._load_listing()
            if item.category == "weapon" and item.is_master
        ]

    def load_master_armor(self) -> list[CatalogItem]:
        return [
            item
            for item in self._load_listing()
            if item.category == "armor" and item.is_master
        ]

    def load_master_containers(self) -> list[CatalogItem]:
        return [
            item
            for item in self._load_listing()
            if item.category == "containers" and item.is_master
        ]

    def load_module_cores(self) -> list[CatalogItem]:
        return [
            item
            for item in self._load_listing()
            if item.category == "weapon_modules" and item.subcategory == "weapon_module_core"
        ]

    def search(self, query: str, *, limit: int = 20) -> list[CatalogItem]:
        query_lower = query.strip().lower()
        if not query_lower:
            return []

        results: list[CatalogItem] = []
        for item in self._load_listing():
            if query_lower in item.name.lower() or query_lower in item.id.lower():
                results.append(item)
                if len(results) >= limit:
                    break
        return results

    def find_by_id(self, item_id: str) -> CatalogItem | None:
        item_id = item_id.strip()
        for item in self._load_listing():
            if item.id == item_id:
                return item
        return None

    def _load_listing(self) -> list[CatalogItem]:
        cached = self._read_cache()
        if cached is not None:
            return cached

        url = LISTING_URLS.get(self.realm)
        if url is None:
            raise ValueError(f"Неизвестный realm: {self.realm}. Доступны: {', '.join(LISTING_URLS)}")

        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()

        items: list[CatalogItem] = []
        if isinstance(data, list):
            for entry in data:
                parsed = self._parse_entry(entry)
                if parsed:
                    items.append(parsed)
        elif isinstance(data, dict):
            for item_id, meta in data.items():
                name = str(meta.get("name", item_id))
                items.append(
                    CatalogItem(
                        id=str(item_id),
                        name=name,
                        category="unknown",
                        subcategory="",
                        is_master=False,
                    )
                )
        else:
            raise ValueError("Неизвестный формат listing.json")

        items.sort(key=lambda item: item.name.lower())
        self._write_cache(items)
        return items

    @staticmethod
    def _parse_entry(entry: dict) -> CatalogItem | None:
        data_path = entry.get("data")
        if not isinstance(data_path, str):
            return None

        item_id = Path(data_path).stem
        if not item_id:
            return None

        name_block = entry.get("name") or {}
        lines = name_block.get("lines") or {}
        name = lines.get("ru") or lines.get("en") or item_id

        parts = Path(data_path).parts
        category = "unknown"
        subcategory = ""
        if "items" in parts:
            idx = parts.index("items")
            if idx + 1 < len(parts):
                category = parts[idx + 1]
            if idx + 2 < len(parts):
                subcategory = parts[idx + 2]

        is_master = entry.get("color") == MASTER_RANK

        return CatalogItem(
            id=item_id,
            name=str(name),
            category=category,
            subcategory=subcategory,
            is_master=is_master,
        )

    def _read_cache(self) -> list[CatalogItem] | None:
        if not self.cache_path.exists():
            return None

        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cached_at = float(payload.get("cached_at", 0))
            if payload.get("version") != self.cache_version:
                return None
            if time.time() - cached_at > self.cache_ttl_seconds:
                return None

            return [
                CatalogItem(
                    id=entry["id"],
                    name=entry["name"],
                    category=entry.get("category", "unknown"),
                    subcategory=entry.get("subcategory", ""),
                    is_master=bool(entry.get("is_master", False)),
                )
                for entry in payload.get("items", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _write_cache(self, items: list[CatalogItem]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.cache_version,
            "cached_at": time.time(),
            "realm": self.realm,
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "category": item.category,
                    "subcategory": item.subcategory,
                    "is_master": item.is_master,
                }
                for item in items
            ],
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
