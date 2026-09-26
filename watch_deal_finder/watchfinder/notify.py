"""Phone push alerts via ntfy (https://ntfy.sh), with a log-only fallback.

ntfy needs no account or bot: install the ntfy app, subscribe to a topic
name, and we publish to that topic. On the public ntfy.sh server the topic
name works like a password (anyone who knows it can read the alerts), so
pick a long random one, or self-host ntfy and use an access token.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

import requests

from .comps import Ident, ebay_sold_url, identify
from .config import AppConfig, SearchConfig
from .market import MarketIndex, Reference, is_hot, is_parts, resolve_reference
from .models import Event, EventKind
from .pricing import format_eur, format_huf
from .storage import Storage

log = logging.getLogger(__name__)

SOURCE_LABELS = {"jofogas": "Jófogás", "ebay": "eBay"}


@dataclass(frozen=True)
class Alert:
    title: str
    body: str
    url: str | None = None          # opened when the notification is tapped
    image_url: str | None = None    # listing thumbnail, shown in the notification
    hot: bool = False
    comps_url: str | None = None    # eBay sold items for the same model, to check the reference


class Notifier(Protocol):
    def send(self, alert: Alert) -> bool: ...


class NtfyNotifier:
    def __init__(
        self,
        topic: str,
        server: str = "https://ntfy.sh",
        token: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 1.0,
    ):
        self.server = server.rstrip("/")
        self.topic = topic
        self.session = session or requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self._sleep = sleep
        self._min_interval = min_interval
        self._last_sent: float | None = None

    def payload(self, alert: Alert) -> dict:
        # JSON publishing (POST to the server root) keeps accents and emoji intact;
        # plain HTTP headers would need special encoding for them.
        data: dict = {
            "topic": self.topic,
            "title": alert.title,
            "message": alert.body,
            "priority": 5 if alert.hot else 4,
            "tags": ["fire"] if alert.hot else ["watch"],
        }
        if alert.url:
            data["click"] = alert.url
            data["actions"] = [{"action": "view", "label": "Open listing", "url": alert.url}]
        if alert.comps_url:
            data.setdefault("actions", []).append({"action": "view", "label": "eBay sold", "url": alert.comps_url})
        if alert.image_url:
            data["attach"] = alert.image_url
        return data

    def send(self, alert: Alert) -> bool:
        payload = self.payload(alert)
        for attempt in range(3):
            if self._last_sent is not None:
                wait = self._min_interval - (time.monotonic() - self._last_sent)
                if wait > 0:
                    self._sleep(wait)
            self._last_sent = time.monotonic()
            try:
                resp = self.session.post(self.server + "/", json=payload, timeout=20)
            except requests.RequestException as exc:
                log.warning("ntfy send failed (%s)", type(exc).__name__)
                self._sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return True
            if resp.status_code == 429 or resp.status_code >= 500:
                # ntfy.sh allows bursts of ~60 messages, then about one every 5 s.
                log.warning("ntfy answered HTTP %s; retrying", resp.status_code)
                self._sleep(10 * (attempt + 1))
                continue
            log.error("ntfy rejected the message: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        return False


class LogNotifier:
    """Used when NTFY_TOPIC is not set: alerts only go to the log file / console."""

    def send(self, alert: Alert) -> bool:
        log.info("ALERT (ntfy not configured): %s\n%s\n%s%s", alert.title, alert.body, alert.url or "",
                 f"\nSold comps: {alert.comps_url}" if alert.comps_url else "")
        return True


def build_notifier(config: AppConfig) -> Notifier:
    s = config.secrets
    if s.ntfy_topic:
        return NtfyNotifier(s.ntfy_topic, server=s.ntfy_server, token=s.ntfy_token)
    log.warning("NTFY_TOPIC not set in .env; alerts will only be logged")
    return LogNotifier()


# -- deciding and formatting ---------------------------------------------


def listing_reference(
    listing, search: SearchConfig, config: AppConfig, index: MarketIndex | None = None
) -> tuple[Reference | None, Ident]:
    """The reference for one listing: the owner's own ref for this watch, else the median
    of its comparable ads, else the search's reference (see market.py)."""
    from .cloudsync import doc_id

    ident = identify(listing.title, listing.details, search.keywords)
    ref = resolve_reference(ident, config.model_references, index, config.eur_huf_rate,
                            search.reference_price_eur, exclude_id=doc_id(listing.source, listing.listing_id))
    return ref, ident


def reference_line(ref: Reference, price_huf: int, rate: float, search_name: str) -> str:
    if ref.source == "market" and ref.stats:
        s = ref.stats
        typical = s.median
        diff = round(100 * (typical - price_huf) / typical)
        where = f"{diff}% below" if diff >= 0 else f"{-diff}% above"
        similar = f"{s.n} similar vague ads" if ref.generic else f"{s.n} similar ads ({ref.key})"
        return (f"📊 typical Jófogás price of {similar}: {format_huf(typical)} "
                f"(middle half {format_huf(s.p25)}–{format_huf(s.p75)}) → {where}")
    margin = ref.eur - price_huf / rate
    pct = round(100 * abs(margin) / ref.eur)
    sign = "+" if margin >= 0 else "−"
    which = f"your ref for '{ref.key}'" if ref.source == "you" else f"{search_name} search ref"
    return f"📈 {which}: {format_eur(ref.eur)} → est. margin {sign}{format_eur(abs(margin))} ({sign}{pct}%)"


def should_alert(event: Event, search: SearchConfig, config: AppConfig, storage: Storage) -> bool:
    listing = event.listing
    if not config.source_notifies(listing.source):
        return False
    if search.max_price_huf is not None and event.price_huf is not None and event.price_huf > search.max_price_huf:
        return False
    row = storage.get(listing.source, listing.listing_id)
    if row is not None and row["user_status"] == "ignore":
        return False
    return not storage.alert_already_sent(listing.source, listing.listing_id, event.price_huf)


def format_alert(event: Event, search: SearchConfig, config: AppConfig, index: MarketIndex | None = None) -> Alert:
    listing = event.listing
    rate = config.eur_huf_rate
    ref, ident = listing_reference(listing, search, config, index)
    hot = is_hot(event.price_huf, ref, rate, config.hot_deal_ratio, listing.title)

    head = "📉 Price drop" if event.kind is EventKind.PRICE_DROP else "🆕 New"
    if hot:
        head = "🔥 " + head
    price_short = format_huf(event.price_huf) if event.price_huf is not None else "no price"
    title = f"{head} · {search.name} · {price_short}"

    lines = [listing.title]
    if event.price_huf is None:
        lines.append("💰 no price given")
    elif listing.currency == "HUF":
        lines.append(f"💰 {format_huf(event.price_huf)} (~{format_eur(event.price_huf / rate)})")
    else:
        lines.append(f"💰 {listing.price:,.2f} {listing.currency} (~{format_huf(event.price_huf)})")

    if event.kind is EventKind.PRICE_DROP and event.old_price_huf and event.price_huf is not None:
        pct = round(100 * (event.old_price_huf - event.price_huf) / event.old_price_huf)
        lines.append(f"↘️ was {format_huf(event.old_price_huf)} (−{pct}%)")

    if ref and event.price_huf is not None:
        lines.append(reference_line(ref, event.price_huf, rate, search.name))
    if is_parts(listing.title):
        lines.append("🔧 looks like parts / defective / accessory")

    where = " · ".join(p for p in (listing.location, SOURCE_LABELS.get(listing.source, listing.source)) if p)
    lines.append(f"📍 {where}")
    comps = ebay_sold_url(ident.query, config.ebay.sold_domain, config.ebay.category_ids)
    return Alert(title=title, body="\n".join(lines), url=listing.url, image_url=listing.thumbnail_url, hot=hot,
                 comps_url=comps)
