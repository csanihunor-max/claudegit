"""Marketplace sources. `build_sources` returns the enabled ones, keyed by name."""

from __future__ import annotations

import logging

from ..config import AppConfig
from ..http import HttpClient
from .base import Source, SourceError
from .ebay import EbaySource
from .jofogas import JofogasSource

log = logging.getLogger(__name__)

__all__ = ["Source", "SourceError", "build_sources"]


def build_sources(config: AppConfig, http: HttpClient) -> dict[str, Source]:
    sources: dict[str, Source] = {}
    if config.jofogas.enabled:
        sources["jofogas"] = JofogasSource(http, config.jofogas)
    if config.ebay.enabled:
        client_id, secret = config.secrets.ebay_client_id, config.secrets.ebay_client_secret
        if client_id and secret:
            sources["ebay"] = EbaySource(http, config.ebay, client_id, secret)
        else:
            log.warning("eBay is enabled in config.yaml but EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are "
                        "missing from .env; skipping eBay")
    return sources
