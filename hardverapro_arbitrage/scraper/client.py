"""Thin, polite HTTP client for fetching hardverapro.hu pages."""
from __future__ import annotations

from ..config import Config
from ..http import FetchError, PoliteClient

__all__ = ["FetchError", "HardveraproClient"]


class HardveraproClient(PoliteClient):
    def __init__(self, config: Config):
        super().__init__(
            user_agent=config.user_agent,
            delay_seconds=config.request_delay_seconds,
            timeout_seconds=config.request_timeout_seconds,
        )
