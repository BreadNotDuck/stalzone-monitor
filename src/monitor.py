from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .api import Lot, PriceEntry, StalzoneClient
from .artifact_meta import (
    ALL_ARTIFACT_QUALITIES,
    potential_labels,
    quality_labels,
    variant_label,
)
from .catalog import CatalogItem, ItemCatalog
from .config import ItemWatch, Settings, load_settings
from .notifier import TelegramNotifier, deal_history_keyboard, format_deal_message
from .storage import SeenLotsStore
from .subscriptions import SubscriptionsStore


@dataclass
class ScanResult:
    notified: int = 0
    scanned: int = 0
    with_lots: int = 0
    candidates: int = 0
    skipped_seen: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"новых: {self.notified} | проверено: {self.scanned} | "
            f"с лотами: {self.with_lots} | кандидатов: {self.candidates} | "
            f"уже видели: {self.skipped_seen}"
        )


@dataclass(frozen=True)
class SaleReference:
    price: int
    count: int
    level: str  # full (3+), low (1-2), none
    prices: tuple[int, ...] = ()
    times: tuple[str, ...] = ()


@dataclass(frozen=True)
class DealCandidate:
    lot: Lot
    average_price: int | None
    reference_count: int | None
    next_lot_price: int | None
    discount_percent: float
    reason: str
    quality: int | None
    potential: int | None
    confidence: str  # confirmed | partial | preliminary
    item_category: str = "artifacts"
    history_prices: tuple[int, ...] = ()
    history_times: tuple[str, ...] = ()


class AuctionMonitor:
    def __init__(
        self,
        settings: Settings,
        client: StalzoneClient,
        store: SeenLotsStore,
        notifier: TelegramNotifier,
        catalog: ItemCatalog | None = None,
        subs_store: SubscriptionsStore | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.store = store
        self.notifier = notifier
        self.subs_store = subs_store
        self.catalog = catalog or ItemCatalog(realm=settings.catalog_realm)
        self._artifact_items: list[CatalogItem] | None = None
        self._master_weapons: list[CatalogItem] | None = None
        self._master_armor: list[CatalogItem] | None = None
        self._containers: list[CatalogItem] | None = None
        self._module_cores: list[CatalogItem] | None = None
        self._stats = ScanResult()

    def reload_settings(self) -> None:
        self.settings = load_settings(self.settings.config_path)

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        print(self._mode_label())
        while True:
            if stop_event and stop_event.is_set():
                break
            self.run_once()
            if not self._sleep_interruptible(self.settings.poll_interval_seconds, stop_event):
                break

    def run_once(self) -> ScanResult:
        self.reload_settings()
        self._stats = ScanResult()
        notified = 0

        custom_ids = {item.id for item in self.settings.custom_items}
        for item in self.settings.custom_items:
            try:
                notified += self._check_item(
                    item, artifact_mode=False, item_category="custom"
                )
            except Exception as exc:
                self._stats.errors += 1
                print(f"[ERROR] {item.id}: {exc}")

        if self.settings.watch_artifacts:
            try:
                notified += self._scan_all_artifacts(custom_ids)
            except Exception as exc:
                self._stats.errors += 1
                print(f"[ERROR] artifacts scan: {exc}")

        try:
            notified += self._scan_all_module_cores(custom_ids)
        except Exception as exc:
            self._stats.errors += 1
            print(f"[ERROR] module cores scan: {exc}")

        try:
            notified += self._scan_category(
                "weapons",
                self._get_master_weapons(),
                custom_ids,
            )
        except Exception as exc:
            self._stats.errors += 1
            print(f"[ERROR] weapons scan: {exc}")

        try:
            notified += self._scan_category(
                "armor",
                self._get_master_armor(),
                custom_ids,
            )
        except Exception as exc:
            self._stats.errors += 1
            print(f"[ERROR] armor scan: {exc}")

        try:
            notified += self._scan_category(
                "containers",
                self._get_containers(),
                custom_ids,
            )
        except Exception as exc:
            self._stats.errors += 1
            print(f"[ERROR] containers scan: {exc}")

        self._stats.notified = notified
        print(f"[SCAN] {self._stats.summary()}")
        return self._stats

    @staticmethod
    def _sleep_interruptible(seconds: int, stop_event: threading.Event | None) -> bool:
        if stop_event is None:
            time.sleep(seconds)
            return True

        for _ in range(seconds):
            if stop_event.is_set():
                return False
            time.sleep(1)
        return True

    def _mode_label(self) -> str:
        qualities = quality_labels(list(self.settings.artifact_qualities))
        potentials = potential_labels(list(self.settings.artifact_potentials))
        parts: list[str] = [f"артефакты ({qualities}, {potentials})"]
        parts.append("мастерское оружие, броня, контейнеры, ядра модулей")
        if self.settings.custom_items:
            parts.append(f"+ {len(self.settings.custom_items)} своих предметов")
        mode = ", ".join(parts)
        return (
            f"Мониторинг ({mode}) на {self.settings.region}, "
            f"интервал {self.settings.poll_interval_seconds} сек."
        )

    def _get_artifact_items(self) -> list[CatalogItem]:
        if self._artifact_items is None:
            self._artifact_items = self.catalog.load_artifacts()
            print(f"Артефактов в каталоге: {len(self._artifact_items)} шт.")
        return self._artifact_items

    def _get_master_weapons(self) -> list[CatalogItem]:
        if self._master_weapons is None:
            self._master_weapons = self.catalog.load_master_weapons()
            print(f"Мастерского оружия в каталоге: {len(self._master_weapons)} шт.")
        return self._master_weapons

    def _get_master_armor(self) -> list[CatalogItem]:
        if self._master_armor is None:
            self._master_armor = self.catalog.load_master_armor()
            print(f"Мастерской брони в каталоге: {len(self._master_armor)} шт.")
        return self._master_armor

    def _get_containers(self) -> list[CatalogItem]:
        if self._containers is None:
            self._containers = self.catalog.load_master_containers()
            print(f"Мастерских контейнеров в каталоге: {len(self._containers)} шт.")
        return self._containers

    def _get_module_cores(self) -> list[CatalogItem]:
        if self._module_cores is None:
            self._module_cores = self.catalog.load_module_cores()
            print(f"Ядер модулей в каталоге: {len(self._module_cores)} шт.")
        return self._module_cores

    def _scan_category(
        self,
        category: str,
        items: list[CatalogItem],
        skip_ids: set[str],
    ) -> int:
        to_scan = [item for item in items if item.id not in skip_ids]
        if not to_scan:
            return 0

        labels = {
            "weapons": "мастерского оружия",
            "armor": "мастерской брони",
            "containers": "мастерских контейнеров",
        }
        label = labels.get(category, category)
        print(
            f"Сканирую {len(to_scan)} {label} "
            f"(потоков: {self.settings.scan_workers})"
        )

        started = time.monotonic()
        sent = 0
        workers = self.settings.scan_workers

        if workers <= 1:
            for index, catalog_item in enumerate(to_scan, start=1):
                try:
                    sent += self._scan_one_simple(catalog_item, category)
                except Exception as exc:
                    self._stats.errors += 1
                    print(f"[ERROR] {catalog_item.id}: {exc}")
                if index % 20 == 0:
                    print(f"  ... {index}/{len(to_scan)}")
        else:
            done = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._scan_one_simple, catalog_item, category): catalog_item
                    for catalog_item in to_scan
                }
                for future in as_completed(futures):
                    catalog_item = futures[future]
                    done += 1
                    try:
                        sent += future.result()
                    except Exception as exc:
                        self._stats.errors += 1
                        print(f"[ERROR] {catalog_item.id}: {exc}")
                    if done % 20 == 0:
                        print(f"  ... {done}/{len(to_scan)}")

        elapsed = time.monotonic() - started
        print(f"  {label}: готово за {elapsed:.0f} сек, сделок: {sent}")
        return sent

    def _scan_one_simple(self, catalog_item: CatalogItem, category: str) -> int:
        self._stats.scanned += 1
        watch = ItemWatch(id=catalog_item.id, name=catalog_item.name)
        return self._check_item(watch, artifact_mode=False, item_category=category)

    def _scan_all_module_cores(self, skip_ids: set[str]) -> int:
        items = self._get_module_cores()
        to_scan = [item for item in items if item.id not in skip_ids]
        if not to_scan:
            return 0

        print(
            f"Сканирую {len(to_scan)} ядер модулей "
            f"(редкости: все, потоков: {self.settings.scan_workers}"
            f"{', турбо' if self.settings.fast_scan else ''})"
        )

        started = time.monotonic()
        sent = 0
        workers = self.settings.scan_workers

        if workers <= 1:
            for index, core in enumerate(to_scan, start=1):
                try:
                    sent += self._scan_one_module_core(core)
                except Exception as exc:
                    self._stats.errors += 1
                    print(f"[ERROR] {core.id}: {exc}")
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._scan_one_module_core, core): core
                    for core in to_scan
                }
                for future in as_completed(futures):
                    core = futures[future]
                    try:
                        sent += future.result()
                    except Exception as exc:
                        self._stats.errors += 1
                        print(f"[ERROR] {core.id}: {exc}")

        elapsed = time.monotonic() - started
        print(f"  ядра модулей: готово за {elapsed:.0f} сек, сделок: {sent}")
        return sent

    def _scan_one_module_core(self, core: CatalogItem) -> int:
        self._stats.scanned += 1
        watch = ItemWatch(id=core.id, name=core.name)
        return self._check_item(
            watch,
            quality_only_mode=True,
            item_category="module_cores",
        )

    def _scan_all_artifacts(self, skip_ids: set[str]) -> int:
        artifacts = self._get_artifact_items()
        all_items = [item for item in artifacts if item.id not in skip_ids]
        if not all_items:
            return 0

        batch_size = self.settings.scan_batch_size
        if batch_size > 0 and batch_size < len(all_items):
            cursor = self.store.get_scan_cursor() % len(all_items)
            to_scan = [all_items[(cursor + i) % len(all_items)] for i in range(batch_size)]
            next_cursor = (cursor + batch_size) % len(all_items)
            self.store.set_scan_cursor(next_cursor)
            batch_label = f"пакет {len(to_scan)}/{len(all_items)}"
        else:
            to_scan = all_items
            batch_label = f"{len(to_scan)}"

        print(
            f"Сканирую {batch_label} артефактов "
            f"(редкости: все, "
            f"заточки: {potential_labels(list(self.settings.artifact_potentials))}, "
            f"потоков: {self.settings.scan_workers}"
            f"{', турбо' if self.settings.fast_scan else ''})"
        )

        started = time.monotonic()
        sent = 0
        workers = self.settings.scan_workers

        if workers <= 1:
            for index, artifact in enumerate(to_scan, start=1):
                try:
                    sent += self._scan_one_artifact(artifact)
                except Exception as exc:
                    self._stats.errors += 1
                    print(f"[ERROR] {artifact.id}: {exc}")
                if index % 20 == 0:
                    print(f"  ... {index}/{len(to_scan)}")
        else:
            done = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._scan_one_artifact, artifact): artifact
                    for artifact in to_scan
                }
                for future in as_completed(futures):
                    artifact = futures[future]
                    done += 1
                    try:
                        sent += future.result()
                    except Exception as exc:
                        self._stats.errors += 1
                        print(f"[ERROR] {artifact.id}: {exc}")
                    if done % 20 == 0:
                        print(f"  ... {done}/{len(to_scan)}")

        elapsed = time.monotonic() - started
        print(f"  готово за {elapsed:.0f} сек, сделок: {sent}")
        return sent

    def _scan_one_artifact(self, artifact: CatalogItem) -> int:
        self._stats.scanned += 1
        watch = ItemWatch(id=artifact.id, name=artifact.name)
        return self._check_item(watch, artifact_mode=True, item_category="artifacts")

    def _check_item(
        self,
        item: ItemWatch,
        *,
        artifact_mode: bool = False,
        quality_only_mode: bool = False,
        item_category: str = "artifacts",
    ) -> int:
        uses_additional = artifact_mode or quality_only_mode
        lots_limit = (
            self.settings.artifact_lots_limit if uses_additional else self.settings.lots_limit
        )
        lots = self.client.get_lots(
            item.id,
            limit=lots_limit,
            sort="buyout_price",
            order="asc",
            with_additional=uses_additional,
        )
        lots = [lot for lot in lots if lot.buyout_price and lot.buyout_price > 0]
        if not lots:
            return 0

        if uses_additional:
            self._stats.with_lots += 1

        if not artifact_mode and not quality_only_mode:
            if len(lots) < 2:
                return 0
            return self._check_simple(item, lots, item_category=item_category)

        if quality_only_mode:
            lots = [
                lot
                for lot in lots
                if lot.quality is not None and lot.quality in ALL_ARTIFACT_QUALITIES
            ]
            if not lots:
                return 0

            sent = 0
            history_cache: dict[str, list[PriceEntry]] = {}
            by_quality: dict[int, list[Lot]] = defaultdict(list)
            for lot in lots:
                if lot.quality is not None:
                    by_quality[lot.quality].append(lot)

            for quality, group in by_quality.items():
                group.sort(key=lambda lot: lot.buyout_price or 0)
                if not self._passes_next_lot_threshold(item, group):
                    continue
                if self.settings.fast_scan:
                    sale_ref = None
                else:
                    sale_ref = self._sale_reference_by_quality(
                        item.id, quality, history_cache
                    )
                candidate = self._find_cheapest_deal(
                    item, group, sale_ref=sale_ref, item_category=item_category
                )
                if candidate is None:
                    continue
                self._stats.candidates += 1
                sent += self._notify_candidate(item, candidate, item_category=item_category)

            return sent

        allowed_potentials = set(self.settings.artifact_potentials)
        lots = [
            lot
            for lot in lots
            if lot.quality is not None
            and lot.quality in ALL_ARTIFACT_QUALITIES
            and lot.potential in allowed_potentials
        ]
        if not lots:
            return 0

        sent = 0
        history_cache: dict[str, list[PriceEntry]] = {}
        by_variant: dict[tuple[int, int], list[Lot]] = defaultdict(list)
        for lot in lots:
            if lot.quality is None or lot.potential is None:
                continue
            by_variant[(lot.quality, lot.potential)].append(lot)

        for (quality, potential), group in by_variant.items():
            group.sort(key=lambda lot: lot.buyout_price or 0)
            if not self._passes_next_lot_threshold(item, group):
                continue
            if self.settings.fast_scan:
                sale_ref = None
            else:
                sale_ref = self._sale_reference(item.id, quality, potential, history_cache)
            candidate = self._find_cheapest_deal(
                item, group, sale_ref=sale_ref, item_category="artifacts"
            )
            if candidate is None:
                continue
            self._stats.candidates += 1
            sent += self._notify_candidate(item, candidate, item_category="artifacts")

        return sent

    def _passes_next_lot_threshold(self, item: ItemWatch, lots: list[Lot]) -> bool:
        if len(lots) < 2:
            return False

        threshold = item.discount_percent
        if threshold is None:
            threshold = self.settings.default_discount_percent

        price = lots[0].buyout_price
        next_price = lots[1].buyout_price
        if not price or not next_price or next_price <= price:
            return False

        discount_vs_next = (1 - price / next_price) * 100
        return discount_vs_next >= threshold

    def _check_simple(
        self,
        item: ItemWatch,
        lots: list[Lot],
        *,
        item_category: str,
    ) -> int:
        lots.sort(key=lambda lot: lot.buyout_price or 0)
        candidate = self._find_cheapest_deal(
            item, lots, item_category=item_category
        )
        if candidate is None:
            return 0
        return self._notify_candidate(item, candidate, item_category=item_category)

    def _sale_reference(
        self,
        item_id: str,
        quality: int,
        potential: int,
        history_cache: dict[str, list[PriceEntry]],
    ) -> SaleReference | None:
        if item_id not in history_cache:
            history_cache[item_id] = self.client.get_price_history(
                item_id, limit=100, with_additional=True
            )
        prices = [
            entry.price
            for entry in history_cache[item_id]
            if entry.price > 0
            and entry.quality == quality
            and entry.potential == potential
        ]
        times = [
            entry.time
            for entry in history_cache[item_id]
            if entry.price > 0
            and entry.quality == quality
            and entry.potential == potential
        ]
        # история API обычно от новых к старым — для графика нужна хронология
        prices = tuple(reversed(prices))
        times = tuple(reversed(times))
        if len(prices) >= 3:
            return SaleReference(int(statistics.median(prices)), len(prices), "full", prices, times)
        if len(prices) >= 1:
            return SaleReference(int(statistics.mean(prices)), len(prices), "low", prices, times)
        return None

    def _sale_reference_by_quality(
        self,
        item_id: str,
        quality: int,
        history_cache: dict[str, list[PriceEntry]],
    ) -> SaleReference | None:
        if item_id not in history_cache:
            history_cache[item_id] = self.client.get_price_history(
                item_id, limit=100, with_additional=True
            )
        prices = [
            entry.price
            for entry in history_cache[item_id]
            if entry.price > 0 and entry.quality == quality
        ]
        times = [
            entry.time
            for entry in history_cache[item_id]
            if entry.price > 0 and entry.quality == quality
        ]
        prices = tuple(reversed(prices))
        times = tuple(reversed(times))
        if len(prices) >= 3:
            return SaleReference(int(statistics.median(prices)), len(prices), "full", prices, times)
        if len(prices) >= 1:
            return SaleReference(int(statistics.mean(prices)), len(prices), "low", prices, times)
        return None

    def _find_cheapest_deal(
        self,
        item: ItemWatch,
        lots: list[Lot],
        *,
        sale_ref: SaleReference | None = None,
        item_category: str = "artifacts",
    ) -> DealCandidate | None:
        """Уведомление только по сравнению со следующим лотом; медиана — справочно."""
        if len(lots) < 2:
            return None

        threshold = item.discount_percent
        if threshold is None:
            threshold = self.settings.default_discount_percent

        cheapest = lots[0]
        next_lot = lots[1]
        price = cheapest.buyout_price
        next_price = next_lot.buyout_price
        if not price or not next_price or next_price <= price:
            return None

        discount_vs_next = (1 - price / next_price) * 100
        if discount_vs_next < threshold:
            return None

        reasons = [
            f"ниже следующего лота на {discount_vs_next:.0f}% ({next_price:,} ₽)".replace(",", " ")
        ]
        best_discount = discount_vs_next
        confidence = "preliminary"
        reference_price: int | None = None
        reference_count: int | None = None

        if sale_ref is None:
            reasons.append("нет истории продаж")
        elif sale_ref.level == "low":
            confidence = "partial"
            reference_price = sale_ref.price
            reference_count = sale_ref.count
            if price < sale_ref.price:
                discount_vs_sales = (1 - price / sale_ref.price) * 100
                reasons.append(
                    f"ниже {sale_ref.count} недавних продаж на {discount_vs_sales:.0f}% "
                    f"({sale_ref.price:,} ₽)".replace(",", " ")
                )
                best_discount = max(best_discount, discount_vs_sales)
            else:
                markup = (price / sale_ref.price - 1) * 100
                reasons.append(
                    f"ориентир по {sale_ref.count} продажам: {sale_ref.price:,} ₽ "
                    f"(лот дороже на {markup:.0f}%)".replace(",", " ")
                )
        else:
            reference_price = sale_ref.price
            reference_count = sale_ref.count
            confidence = "confirmed" if price < sale_ref.price else "partial"
            if price < sale_ref.price:
                discount_vs_sales = (1 - price / sale_ref.price) * 100
                reasons.append(
                    f"ниже медианы {sale_ref.count} продаж на {discount_vs_sales:.0f}% "
                    f"({sale_ref.price:,} ₽)".replace(",", " ")
                )
                best_discount = max(best_discount, discount_vs_sales)
            else:
                markup = (price / sale_ref.price - 1) * 100
                reasons.append(
                    f"медиана {sale_ref.count} продаж: {sale_ref.price:,} ₽ "
                    f"(лот дороже на {markup:.0f}%)".replace(",", " ")
                )

        return DealCandidate(
            lot=cheapest,
            average_price=reference_price,
            reference_count=reference_count,
            next_lot_price=next_price,
            discount_percent=best_discount,
            reason="; ".join(reasons),
            quality=cheapest.quality,
            potential=cheapest.potential,
            confidence=confidence,
            item_category=item_category,
            history_prices=sale_ref.prices if sale_ref else (),
            history_times=sale_ref.times if sale_ref else (),
        )

    def _recipients_for_candidate(
        self,
        *,
        item_category: str,
        quality: int | None,
    ) -> list[str]:
        recipients: list[str] = []
        admin_id = str(self.settings.telegram_chat_id) if self.settings.telegram_chat_id else None

        def wants(chat_id: str) -> bool:
            if item_category == "custom":
                return True
            if self.subs_store and not self.subs_store.receives_notifications(chat_id):
                return False
            if item_category == "artifacts":
                if quality is None or not self.subs_store:
                    return quality is None and self.subs_store is None
                return quality in self.subs_store.get_enabled_qualities(chat_id)
            if item_category == "module_cores":
                if quality is None or not self.subs_store:
                    return quality is None and self.subs_store is None
                return quality in self.subs_store.get_enabled_core_qualities(chat_id)
            if self.subs_store and not self.subs_store.wants_lot_category(chat_id, item_category):
                return False
            return True

        if admin_id and wants(admin_id):
            recipients.append(admin_id)
        if self.subs_store:
            for chat_id in self.subs_store.active_chat_ids():
                if chat_id != admin_id and wants(chat_id):
                    recipients.append(chat_id)
        return recipients

    def _notify_candidate(
        self,
        item: ItemWatch,
        candidate: DealCandidate,
        *,
        item_category: str,
    ) -> int:
        lot_key = SeenLotsStore.lot_key(
            candidate.lot.item_id,
            candidate.lot.buyout_price or 0,
            candidate.lot.start_time,
            candidate.lot.end_time,
            candidate.lot.amount,
            quality=candidate.quality,
            potential=candidate.potential,
        )
        recipients = self._recipients_for_candidate(
            item_category=item_category,
            quality=candidate.quality,
        )
        if not recipients:
            return 0

        sent = 0
        buyout = candidate.lot.buyout_price or 0
        next_price = candidate.next_lot_price or 0
        discount_vs_next = (
            (1 - buyout / next_price) * 100 if next_price > 0 and buyout > 0 else 0.0
        )
        profit_gap = 0
        if next_price > 0:
            profit_gap = int(
                round(next_price * (1 - self.settings.auction_fee_percent / 100)) - buyout
            )

        for target in recipients:
            if self.subs_store:
                if self.subs_store.is_item_muted(target, item.id):
                    continue
                balance = self.subs_store.get_max_balance(target)
                if balance > 0 and buyout > balance:
                    continue
                min_pct = self.subs_store.get_min_profit_percent(
                    target, default=self.settings.default_discount_percent
                )
                min_amount = self.subs_store.get_min_profit_amount(target, default=0)
                if discount_vs_next < min_pct or profit_gap < min_amount:
                    continue
            threshold = self.settings.above_reference_percent
            if self.subs_store:
                threshold = self.subs_store.get_above_reference_percent(
                    target, default=self.settings.above_reference_percent
                )
            avg = candidate.average_price
            buyout_price = candidate.lot.buyout_price or 0
            no_median = not avg or avg <= 0
            if (
                self.subs_store
                and no_median
                and not self.subs_store.get_show_no_median(target)
            ):
                continue
            # личный фильтр: не слать лоты ≥ порога выше медианы
            if (
                self.subs_store
                and not self.subs_store.get_show_above_median(target)
                and avg
                and avg > 0
                and buyout_price > avg
            ):
                markup = (buyout_price / avg - 1) * 100
                if markup + 1e-9 >= threshold:
                    continue
            if not self.store.try_claim(
                lot_key, target, item.id, candidate.lot.buyout_price or 0
            ):
                self._stats.skipped_seen += 1
                continue
            personal_message = format_deal_message(
                item_name=item.name or item.id,
                item_id=item.id,
                buyout_price=candidate.lot.buyout_price or 0,
                amount=candidate.lot.amount,
                average_price=candidate.average_price,
                reference_count=candidate.reference_count,
                next_lot_price=candidate.next_lot_price,
                discount_percent=candidate.discount_percent,
                end_time=candidate.lot.end_time,
                reason=candidate.reason,
                quality=candidate.quality,
                potential=candidate.potential,
                confidence=candidate.confidence,
                auction_fee_percent=self.settings.auction_fee_percent,
                next_lot_reference_percent=self.settings.next_lot_reference_percent,
                above_reference_percent=threshold,
                history_prices=list(candidate.history_prices) or None,
                history_times=list(candidate.history_times) or None,
            )
            markup = deal_history_keyboard(
                item_id=item.id,
                quality=candidate.quality,
                potential=candidate.potential,
            )
            if self.notifier.send(personal_message, chat_id=target, reply_markup=markup):
                sent += 1
            else:
                self.store.unclaim(lot_key, target)
        if sent:
            if candidate.potential is not None:
                variant = variant_label(candidate.quality, candidate.potential)
            else:
                variant = quality_labels(
                    [candidate.quality] if candidate.quality is not None else []
                )
            print(
                f"[DEAL] {item.name or item.id} ({variant}): "
                f"{candidate.lot.buyout_price} -> {sent} чат(ов)"
            )
            return 1
        return 0
