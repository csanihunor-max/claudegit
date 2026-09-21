"""Generic polite HTTP client: one request in flight, a floor delay between
requests regardless of how many URLs get fetched, and a raised FetchError
instead of a raw exception. Shared by every site-specific scraper client so
the throttling logic exists exactly once.
"""
from __future__ import annotations

import time

import requests


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(self, *, user_agent: str, delay_seconds: float, timeout_seconds: float):
        self._delay_seconds = delay_seconds
        self._timeout_seconds = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.5",
            }
        )
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str) -> str:
        self._throttle()
        try:
            response = self._session.get(url, timeout=self._timeout_seconds)
        except requests.RequestException as exc:
            raise FetchError(f"request to {url} failed: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()

        if response.status_code != 200:
            raise FetchError(f"request to {url} returned HTTP {response.status_code}")

        response.encoding = response.encoding or "utf-8"
        return response.text

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
