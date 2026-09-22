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
    # No silent fallback to a real URL list here on purpose -- unset means
    # unset, and validate() below refuses to run rather than kick off
    # unbounded live network activity nobody explicitly asked for. See
    # categories.py's DEFAULT_SEARCH_URLS for this bot's curated category
    # list, and .env.example for it pre-filled as a real starting value.
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

    # A group of "comparable" listings whose prices disagree with each
    # other by more than this ratio (max/min) isn't trusted as a market
    # reference at all — checked against real data: a generic title like
    # "PS4 játékok" ("PS4 games") groups differently-sized game bundles
    # under one identical-looking key, with a 3.6-4x spread; a genuinely
    # comparable product (a specific console/headset model, independently
    # priced by different sellers) sits under 1.5x. 3.0 is a deliberately
    # conservative line between them.
    max_group_spread_ratio: float = field(default_factory=lambda: _env_float("HA_MAX_GROUP_SPREAD_RATIO", 3.0))

    # A listing is flagged as a deal when its price is at least this far
    # below the item's rolling market reference price. Lowered twice: 0.20
    # -> 0.15 when retail comparison was dropped (árukereső.hu sits behind
    # a Cloudflare JS challenge no plain HTTP scraper can pass, confirmed
    # by fetching it directly and getting a "Just a moment..." challenge
    # page rather than any product markup, so used-median became the only
    # signal), then -> 0.05 to surface more listings still. This is now
    # close to the noise floor -- a small, ordinary price difference
    # between two sellers can clear 5% on its own, so more of what shows
    # up here will be a modest, real markdown rather than a standout deal.
    deal_discount_threshold: float = field(default_factory=lambda: _env_float("HA_DEAL_THRESHOLD", 0.05))

    # Extra required discount, on top of deal_discount_threshold, when a
    # reference price is backed by only the bare minimum number of other
    # listings -- shrinking towards 0 as more comparables accumulate. Real
    # problem this catches: checked against every deal ever flagged in
    # production, ALL of them were backed by only 2-4 comparables (a
    # median of 2 prices is just their average -- no robustness at all,
    # unlike a median of 10), yet a razor-thin 2-listing coincidence was
    # trusted exactly as much as a well-established double-digit-sample
    # market price. margin / (sample_size - 1): at the floor of 2 samples
    # the full margin applies (deal_discount_threshold + 0.10 required);
    # by ~10 samples it's added barely 1 percentage point.
    low_sample_discount_margin: float = field(
        default_factory=lambda: _env_float("HA_LOW_SAMPLE_MARGIN", 0.10)
    )

    # A discount at or above this is treated as implausible rather than a
    # great find, and rejected outright -- real examples from a single
    # live cycle: "Samsung Monitor" at 90.9% off (11,000 -> 1,000 HUF, a
    # reference price absurdly low for any monitor, meaning two
    # completely different unnamed/unmodeled monitors got treated as the
    # same product), "Nintendo Switch OLED" at 60%, "Eladó blu-ray
    # filmek" ("blu-ray movies for sale") at 64.7% -- a generic-enough
    # title that whatever it matched against wasn't really the same
    # product either. A real, genuinely-priced used item essentially
    # never sells at less than half its own recent resale median; when
    # the math says otherwise, the far more likely explanation is a bad
    # title match or a data entry error in one of the listings, not an
    # extraordinary bargain.
    max_plausible_discount_fraction: float = field(
        default_factory=lambda: _env_float("HA_MAX_PLAUSIBLE_DISCOUNT", 0.5)
    )

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

    # A category page shows ~100 listings before requiring pagination.
    # `?offset=100`, `?offset=200`, ... reaches further pages — this is
    # the category BROWSE endpoint's own pagination, not the *search*
    # endpoint's (`keres.php?...offset=`) that robots.txt disallows, so
    # it's fine to follow. 1 = only the first page (old behavior); each
    # additional page is one more request per category per cycle, so
    # weigh this against how many categories are configured and how
    # tight HA_POLL_INTERVAL_SECONDS is. Raised from an earlier 3: with
    # used-median as the only comparison now (see HA_DEAL_THRESHOLD),
    # deeper coverage per category is the direct lever for finding more
    # duplicate listings to compare against -- pagination already stops
    # early on its own (see pipeline.py's wrap-around handling) for any
    # category smaller than this, so raising the cap only costs extra
    # requests on categories actually deep enough to use them.
    max_pages_per_category: int = field(default_factory=lambda: _env_int("HA_MAX_PAGES_PER_CATEGORY", 6))

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
