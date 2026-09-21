"""Thin, polite HTTP client for fetching árukereső.hu pages."""
from __future__ import annotations

from ..config import Config
from ..http import FetchError, PoliteClient

__all__ = ["FetchError", "ArukeresoClient"]


class ArukeresoClient(PoliteClient):
    def __init__(self, config: Config):
        super().__init__(
            user_agent=config.user_agent,
            delay_seconds=config.retail_request_delay_seconds,
            timeout_seconds=config.retail_request_timeout_seconds,
        )
