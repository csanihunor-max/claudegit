"""Thin, polite HTTP client for fetching hardverapro.hu pages."""
from __future__ import annotations

import logging
import time

import requests

from ..config import Config

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


class HardveraproClient:
    def __init__(self, config: Config):
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.5",
            }
        )
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        """Never hammer the site — one request in flight, with a floor gap
        between requests regardless of how many search URLs are configured.
        """
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._config.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str) -> str:
        self._throttle()
        try:
            response = self._session.get(url, timeout=self._config.request_timeout_seconds)
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

    def __enter__(self) -> "HardveraproClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
