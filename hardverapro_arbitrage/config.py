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

    # Minimum number of OTHER listings of the same item before we trust
    # the computed market reference enough to flag deals against it (a
    # median of 1 other listing isn't really a "market" — it's just
    # "cheaper than one specific competitor", too easy for a single
    # oddly-priced listing to skew). 2 is the floor that still means
    # something; checked against real collected data, most duplicate
    # groups only ever reach 2 other listings, so requiring 3 silently
    # discarded most of them rather than reflecting genuine caution.
    min_samples_for_reference: int = field(default_factory=lambda: _env_int("HA_MIN_SAMPLES", 2))

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

    # Retail (árukereső.hu) comparison — secondary to the used-median
    # comparison above. Used-median stays the PRIMARY signal: a listing is
    # only evaluated against retail when there either isn't enough used-
    # listing history yet to trust a used-median reference, or the used-
    # median discount didn't clear its own threshold. Because almost any
    # used item is *somewhat* cheaper than a new one — that alone means
    # nothing — this threshold defaults much higher than the used-median
    # one, so only a genuinely exceptional price relative to retail
    # qualifies.
    retail_enabled: bool = field(default_factory=lambda: os.environ.get("HA_RETAIL_ENABLED", "true").lower() != "false")
    retail_deal_threshold: float = field(default_factory=lambda: _env_float("HA_RETAIL_DEAL_THRESHOLD", 0.45))

    # A retail search result is only trusted as "the same product" above
    # this confidence (see retail/matcher.py) — below it, no retail
    # comparison is made for that listing rather than risk comparing
    # against the wrong product's price.
    retail_min_match_confidence: float = field(
        default_factory=lambda: _env_float("HA_RETAIL_MIN_MATCH_CONFIDENCE", 0.6)
    )

    # Retail prices barely move hour to hour, so they're cached per
    # normalized item and only refetched after this many days.
    retail_cache_days: int = field(default_factory=lambda: _env_int("HA_RETAIL_CACHE_DAYS", 7))

    # Hard cap on retail lookups per scrape cycle — a lookup is a real
    # request to a site this bot doesn't own, and doing one per listing
    # (there can be hundreds per cycle) would be both slow and impolite.
    # Coverage builds up gradually across cycles instead of all at once.
    retail_max_lookups_per_cycle: int = field(
        default_factory=lambda: _env_int("HA_RETAIL_MAX_LOOKUPS_PER_CYCLE", 15)
    )

    retail_request_timeout_seconds: float = field(
        default_factory=lambda: _env_float("HA_RETAIL_REQUEST_TIMEOUT", 15.0)
    )
    retail_request_delay_seconds: float = field(
        default_factory=lambda: _env_float("HA_RETAIL_REQUEST_DELAY", 2.0)
    )

    def validate(self) -> None:
        if not self.search_urls:
            raise ValueError(
                "No search URLs configured. Set HA_SEARCH_URLS to one or more "
                "comma-separated hardverapro.hu search-result URLs."
            )
