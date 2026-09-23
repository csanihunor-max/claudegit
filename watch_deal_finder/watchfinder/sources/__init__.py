"""Marketplace sources. `build_sources` returns the enabled ones, keyed by name."""

from __future__ import annotations

import logging

from ..config import AppConfig
from ..http import HttpClient
from .base import Source, SourceError
from .jofogas import JofogasSource

log = logging.getLogger(__name__)

__all__ = ["Source", "SourceError", "build_sources"]


def build_sources(config: AppConfig, http: HttpClient) -> dict[str, Source]:
    sources: dict[str, Source] = {}
    if config.jofogas.enabled:
        sources["jofogas"] = JofogasSource(http, config.jofogas)
    return sources
