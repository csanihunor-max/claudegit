"""Loading and validating config.yaml plus secrets from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

MIN_POLL_INTERVAL_MINUTES = 10
KNOWN_SOURCES = ("jofogas", "ebay")
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; WatchDealFinder/1.0; personal listing monitor)"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    name: str
    keywords: tuple[str, ...]
    sources: tuple[str, ...]
    max_price_huf: int | None = None
    reference_price_eur: float | None = None


@dataclass(frozen=True)
class JofogasConfig:
    enabled: bool = True
    # URL path segments under /magyarorszag/ to search in. "karorak-" = men's watches,
    # "karorak" = women's watches, "" = all categories.
    categories: tuple[str, ...] = ("karorak-",)
    notify: bool = True


@dataclass(frozen=True)
class EbayConfig:
    enabled: bool = False
    marketplace: str = "EBAY_DE"
    category_ids: str = "31387"  # Wristwatches
    limit: int = 50
    # eBay is mainly for price comparison; alerts for eBay listings are off by default.
    notify: bool = False


@dataclass(frozen=True)
class Secrets:
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None


@dataclass(frozen=True)
class AppConfig:
    searches: tuple[SearchConfig, ...]
    blacklist: tuple[str, ...] = ()
    category_filter: tuple[str, ...] = ()
    title_must_match: bool = True
    poll_interval_minutes: float = 15
    request_delay_seconds: tuple[float, float] = (3.0, 8.0)
    eur_huf_rate: float = 395.0
    hot_deal_ratio: float = 0.5
    silent_first_pass: bool = True
    gone_check_after_hours: float = 6.0
    max_gone_checks_per_pass: int = 5
    user_agent: str = DEFAULT_USER_AGENT
    database: Path = Path("data/watchfinder.sqlite3")
    log_file: Path = Path("logs/watchfinder.log")
    jofogas: JofogasConfig = field(default_factory=JofogasConfig)
    ebay: EbayConfig = field(default_factory=EbayConfig)
    secrets: Secrets = field(default_factory=Secrets)

    def search(self, name: str) -> SearchConfig | None:
        return next((s for s in self.searches if s.name == name), None)

    def source_notifies(self, source: str) -> bool:
        return {"jofogas": self.jofogas.notify, "ebay": self.ebay.notify}.get(source, True)


def load_config(path: str | Path = "config.yaml", env_file: str | Path | None = ".env") -> AppConfig:
    path = Path(path)
    if env_file:
        # Look next to config.yaml first, so running from another directory still works.
        load_dotenv(path.parent / env_file) or load_dotenv(env_file)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    return parse_config(raw, base_dir=path.parent, environ=os.environ)


def parse_config(raw: dict[str, Any], base_dir: Path = Path("."), environ: Any = None) -> AppConfig:
    environ = environ if environ is not None else {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must be a mapping")

    interval = float(raw.get("poll_interval_minutes", 15))
    if interval < MIN_POLL_INTERVAL_MINUTES:
        raise ConfigError(f"poll_interval_minutes must be at least {MIN_POLL_INTERVAL_MINUTES} (got {interval:g})")

    delay = raw.get("request_delay_seconds", [3, 8])
    if isinstance(delay, (int, float)):
        delay = [delay, delay]
    if len(delay) != 2 or float(delay[0]) < 1 or float(delay[1]) < float(delay[0]):
        raise ConfigError("request_delay_seconds must be [min, max] with 1 <= min <= max")

    rate = float(raw.get("eur_huf_rate", 395))
    if rate <= 0:
        raise ConfigError("eur_huf_rate must be positive")

    sources_raw = raw.get("sources") or {}
    jf = sources_raw.get("jofogas") or {}
    eb = sources_raw.get("ebay") or {}
    jofogas = JofogasConfig(
        enabled=bool(jf.get("enabled", True)),
        categories=tuple(str(c) for c in jf.get("categories", ["karorak-"])),
        notify=bool(jf.get("notify", True)),
    )
    ebay = EbayConfig(
        enabled=bool(eb.get("enabled", False)),
        marketplace=str(eb.get("marketplace", "EBAY_DE")),
        category_ids=str(eb.get("category_ids", "31387")),
        limit=int(eb.get("limit", 50)),
        notify=bool(eb.get("notify", False)),
    )

    searches = tuple(_parse_search(s, i) for i, s in enumerate(raw.get("searches") or []))
    if not searches:
        raise ConfigError("config.yaml needs at least one entry under 'searches'")
    names = [s.name for s in searches]
    if len(set(names)) != len(names):
        raise ConfigError("search names must be unique")

    return AppConfig(
        searches=searches,
        blacklist=tuple(str(w) for w in raw.get("blacklist") or []),
        category_filter=tuple(str(c) for c in raw.get("category_filter") or []),
        title_must_match=bool(raw.get("title_must_match", True)),
        poll_interval_minutes=interval,
        request_delay_seconds=(float(delay[0]), float(delay[1])),
        eur_huf_rate=rate,
        hot_deal_ratio=float(raw.get("hot_deal_ratio", 0.5)),
        silent_first_pass=bool(raw.get("silent_first_pass", True)),
        gone_check_after_hours=float(raw.get("gone_check_after_hours", 6)),
        max_gone_checks_per_pass=int(raw.get("max_gone_checks_per_pass", 5)),
        user_agent=str(raw.get("user_agent") or DEFAULT_USER_AGENT),
        database=_resolve(base_dir, raw.get("database", "data/watchfinder.sqlite3")),
        log_file=_resolve(base_dir, raw.get("log_file", "logs/watchfinder.log")),
        jofogas=jofogas,
        ebay=ebay,
        secrets=Secrets(
            telegram_bot_token=environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=environ.get("TELEGRAM_CHAT_ID") or None,
            ebay_client_id=environ.get("EBAY_CLIENT_ID") or None,
            ebay_client_secret=environ.get("EBAY_CLIENT_SECRET") or None,
        ),
    )


def _parse_search(raw: Any, index: int) -> SearchConfig:
    if not isinstance(raw, dict) or not raw.get("name"):
        raise ConfigError(f"searches[{index}] needs a 'name'")
    name = str(raw["name"])
    keywords = raw.get("keywords")
    if isinstance(keywords, str):
        keywords = [keywords]
    if not keywords:
        raise ConfigError(f"search '{name}' needs at least one keyword")
    sources = raw.get("sources") or ["jofogas"]
    if isinstance(sources, str):
        sources = [sources]
    unknown = [s for s in sources if s not in KNOWN_SOURCES]
    if unknown:
        raise ConfigError(f"search '{name}': unknown source(s) {unknown}; known: {list(KNOWN_SOURCES)}")
    max_price = raw.get("max_price_huf")
    ref = raw.get("reference_price_eur")
    return SearchConfig(
        name=name,
        keywords=tuple(str(k) for k in keywords),
        sources=tuple(sources),
        max_price_huf=int(max_price) if max_price is not None else None,
        reference_price_eur=float(ref) if ref is not None else None,
    )


def _resolve(base_dir: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else base_dir / p
