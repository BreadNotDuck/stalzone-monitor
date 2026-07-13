from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .artifact_meta import parse_potential, parse_quality


class StalzoneApiError(Exception):
    pass


RETRYABLE_EXCEPTIONS = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

@dataclass(frozen=True)
class Lot:
    item_id: str
    amount: int
    start_price: int
    current_price: int | None
    buyout_price: int | None
    start_time: str
    end_time: str
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def quality(self) -> int | None:
        return parse_quality(self.additional)

    @property
    def potential(self) -> int | None:
        return parse_potential(self.additional)


@dataclass(frozen=True)
class PriceEntry:
    amount: int
    price: int
    time: str
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def quality(self) -> int | None:
        return parse_quality(self.additional)

    @property
    def potential(self) -> int | None:
        return parse_potential(self.additional)


class StalzoneClient:
    def __init__(
        self,
        *,
        base_url: str,
        region: str,
        api_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        request_delay_seconds: float = 0.15,
        max_retries: int = 5,
        pool_size: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.region = region.upper()
        self.api_token = api_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.max_retries = max(1, max_retries)
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()
        self._local = threading.local()
        self._pool_size = max(4, pool_size)

        if not api_token and not (client_id and client_secret):
            raise ValueError(
                "Нужен STALZONE_API_TOKEN или пара STALZONE_CLIENT_ID/STALZONE_CLIENT_SECRET"
            )

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=self._pool_size,
            pool_maxsize=self._pool_size,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._make_session()
            self._local.session = session
        return session

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        else:
            headers["Client-Id"] = self.client_id or ""
            headers["Client-Secret"] = self.client_secret or ""
        return headers

    def _throttle(self) -> None:
        if self.request_delay_seconds <= 0:
            return
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.request_delay_seconds:
                time.sleep(self.request_delay_seconds - elapsed)
            self._last_request_at = time.monotonic()

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._throttle()
        url = f"{self.base_url}/{self.region}{path}"
        headers = self._headers()
        session = self._get_session()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(15, 60),
                )

                if response.status_code == 429:
                    reset = response.headers.get("X-Ratelimit-Reset")
                    wait_seconds = 5
                    if reset:
                        try:
                            wait_seconds = max(1, int(reset) - int(time.time()))
                        except ValueError:
                            pass
                    time.sleep(wait_seconds)
                    continue

                if not response.ok:
                    raise StalzoneApiError(
                        f"API {response.status_code} для {path}: {response.text[:300]}"
                    )

                return response.json()
            except RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait_seconds = min(30, 2**attempt + 1)
                    print(
                        f"[API] {path}: {type(exc).__name__}, "
                        f"повтор {attempt + 2}/{self.max_retries} через {wait_seconds}с"
                    )
                    time.sleep(wait_seconds)
                    continue
            except requests.exceptions.RequestException as exc:
                raise StalzoneApiError(f"Ошибка сети для {path}: {exc}") from exc

        raise StalzoneApiError(
            f"Не удалось получить {path} после {self.max_retries} попыток: {last_error}"
        ) from last_error

    def get_lots(
        self,
        item_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        sort: str = "buyout_price",
        order: str = "asc",
        with_additional: bool = True,
    ) -> list[Lot]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "order": order,
        }
        if with_additional:
            params["additional"] = "true"

        data = self._request(f"/auction/{item_id}/lots", params=params)
        lots_raw = data.get("lots") if isinstance(data, dict) else data
        if not lots_raw:
            return []

        lots: list[Lot] = []
        for entry in lots_raw:
            additional = entry.get("additional") or {}
            if not isinstance(additional, dict):
                additional = {}
            lots.append(
                Lot(
                    item_id=str(entry.get("itemId", item_id)),
                    amount=int(entry.get("amount", 1)),
                    start_price=int(entry.get("startPrice", 0)),
                    current_price=entry.get("currentPrice"),
                    buyout_price=entry.get("buyoutPrice"),
                    start_time=str(entry.get("startTime", "")),
                    end_time=str(entry.get("endTime", "")),
                    additional=additional,
                )
            )
        return lots

    def get_price_history(
        self,
        item_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        with_additional: bool = True,
    ) -> list[PriceEntry]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if with_additional:
            params["additional"] = "true"

        data = self._request(f"/auction/{item_id}/history", params=params)
        prices_raw = data.get("prices") if isinstance(data, dict) else data
        if not prices_raw:
            return []

        entries: list[PriceEntry] = []
        for entry in prices_raw:
            additional = entry.get("additional") or {}
            if not isinstance(additional, dict):
                additional = {}
            entries.append(
                PriceEntry(
                    amount=int(entry.get("amount", 1)),
                    price=int(entry.get("price", 0)),
                    time=str(entry.get("time", "")),
                    additional=additional,
                )
            )
        return entries
