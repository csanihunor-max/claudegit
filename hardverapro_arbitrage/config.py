"""Runtime configuration.

Everything here is overridable via environment variables so the same code
runs unchanged in a cron job, a systemd timer, or a container. Search URLs
are the actual hardverapro.hu search-result pages you want polled (copy
them straight from the browser address bar after setting up filters like
category/price range on the site itself).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass
class Config:
    # One or more hardverapro.hu search-result URLs to poll each cycle.
    search_urls: list[str] = field(default_factory=lambda: _env_list("HA_SEARCH_URLS"))

    # How often to run a full scrape cycle.
    poll_interval_seconds: int = field(default_factory=lambda: _env_int("HA_POLL_INTERVAL_SECONDS", 3600))

    # Minimum number of historical price points for an item before we trust
    # the computed market reference enough to flag deals against it.
    min_samples_for_reference: int = field(default_factory=lambda: _env_int("HA_MIN_SAMPLES", 3))

    # A listing is flagged as a deal when its price is at least this far
    # below the item's rolling market reference price.
    deal_discount_threshold: float = field(default_factory=lambda: _env_float("HA_DEAL_THRESHOLD", 0.20))

    # How many days of price history feed the rolling market reference.
    reference_window_days: int = field(default_factory=lambda: _env_int("HA_REFERENCE_WINDOW_DAYS", 90))

    # Ignore listings above this price entirely (0 = no cap). Useful to
    # exclude bundles/lots that skew the per-item reference price.
    max_price: float = field(default_factory=lambda: _env_float("HA_MAX_PRICE", 0))

    db_path: str = field(default_factory=lambda: os.environ.get("HA_DB_PATH", "hardverapro_arbitrage.sqlite3"))

    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "HA_USER_AGENT",
            "Mozilla/5.0 (compatible; hardverapro-arbitrage-bot/0.1; +personal use)",
        )
    )
    request_timeout_seconds: float = field(default_factory=lambda: _env_float("HA_REQUEST_TIMEOUT", 15.0))
    request_delay_seconds: float = field(default_factory=lambda: _env_float("HA_REQUEST_DELAY", 2.0))

    telegram_bot_token: str | None = field(default_factory=lambda: os.environ.get("HA_TELEGRAM_BOT_TOKEN") or None)
    telegram_chat_id: str | None = field(default_factory=lambda: os.environ.get("HA_TELEGRAM_CHAT_ID") or None)

    # Web dashboard (`python -m hardverapro_arbitrage serve`). Bound to all
    # interfaces by default so it's reachable from other devices on your
    # network/VPN, not just localhost on the machine running it — put it
    # behind a tunnel (Tailscale, SSH -L, a reverse proxy) for phone access
    # away from home, don't expose it to the open internet unauthenticated.
    web_host: str = field(default_factory=lambda: os.environ.get("HA_WEB_HOST", "0.0.0.0"))
    web_port: int = field(default_factory=lambda: _env_int("HA_WEB_PORT", 8765))

    # How far back the dashboard looks for deals, and how many it lists.
    deals_list_window_days: int = field(default_factory=lambda: _env_int("HA_DEALS_LIST_WINDOW_DAYS", 14))
    deals_list_limit: int = field(default_factory=lambda: _env_int("HA_DEALS_LIST_LIMIT", 200))

    def validate(self) -> None:
        if not self.search_urls:
            raise ValueError(
                "No search URLs configured. Set HA_SEARCH_URLS to one or more "
                "comma-separated hardverapro.hu search-result URLs."
            )
