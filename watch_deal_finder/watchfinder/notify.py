"""Telegram alerts (with a console fallback when no bot token is configured)."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Callable, Protocol

import requests

from .config import AppConfig, SearchConfig
from .models import Event, EventKind
from .pricing import format_eur, format_huf
from .storage import Storage

log = logging.getLogger(__name__)

SOURCE_LABELS = {"jofogas": "Jófogás", "ebay": "eBay"}


class Notifier(Protocol):
    def send(self, text: str) -> bool: ...


class TelegramNotifier:
    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        token: str,
        chat_id: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 1.1,  # Telegram asks for at most ~1 message/second per chat
    ):
        self.url = self.API.format(token=token)
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self._sleep = sleep
        self._min_interval = min_interval
        self._last_sent: float | None = None

    def send(self, text: str) -> bool:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
        for attempt in range(3):
            if self._last_sent is not None:
                wait = self._min_interval - (time.monotonic() - self._last_sent)
                if wait > 0:
                    self._sleep(wait)
            self._last_sent = time.monotonic()
            try:
                resp = self.session.post(self.url, json=payload, timeout=20)
            except requests.RequestException as exc:
                log.warning("Telegram send failed (%s)", type(exc).__name__)  # never log the URL: it has the token
                self._sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                try:
                    retry_after = float(resp.json().get("parameters", {}).get("retry_after", 5))
                except ValueError:
                    retry_after = 5.0
                log.warning("Telegram rate limit hit; waiting %.0fs", retry_after)
                self._sleep(retry_after)
                continue
            if resp.status_code >= 500:
                self._sleep(5 * (attempt + 1))
                continue
            try:
                description = resp.json().get("description", "")
            except ValueError:
                description = resp.text[:200]
            log.error("Telegram rejected the message: HTTP %s %s", resp.status_code, description)
            return False
        return False


class ConsoleNotifier:
    """Used when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are missing: alerts go to the log."""

    def send(self, text: str) -> bool:
        log.info("ALERT (Telegram not configured):\n%s", _strip_tags(text))
        return True


def build_notifier(config: AppConfig) -> Notifier:
    s = config.secrets
    if s.telegram_bot_token and s.telegram_chat_id:
        return TelegramNotifier(s.telegram_bot_token, s.telegram_chat_id)
    log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env; alerts will only be logged")
    return ConsoleNotifier()


# -- deciding and formatting ---------------------------------------------


def is_hot(price_huf: int | None, search: SearchConfig, config: AppConfig) -> bool:
    if price_huf is None or not search.reference_price_eur:
        return False
    return price_huf <= search.reference_price_eur * config.eur_huf_rate * config.hot_deal_ratio


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


def format_alert(event: Event, search: SearchConfig, config: AppConfig) -> str:
    listing = event.listing
    rate = config.eur_huf_rate
    esc = html.escape

    head = "📉 Price drop" if event.kind is EventKind.PRICE_DROP else "🆕 New listing"
    if is_hot(event.price_huf, search, config):
        head = "🔥 " + head
    lines = [f"{head} · {esc(search.name)}", f"<b>{esc(listing.title)}</b>"]

    if event.price_huf is None:
        lines.append("💰 no price given")
    elif listing.currency == "HUF":
        lines.append(f"💰 {format_huf(event.price_huf)} (~{format_eur(event.price_huf / rate)})")
    else:
        lines.append(f"💰 {listing.price:,.2f} {esc(listing.currency)} (~{format_huf(event.price_huf)})")

    if event.kind is EventKind.PRICE_DROP and event.old_price_huf and event.price_huf is not None:
        pct = round(100 * (event.old_price_huf - event.price_huf) / event.old_price_huf)
        lines.append(f"↘️ was {format_huf(event.old_price_huf)} (−{pct}%)")

    if search.reference_price_eur and event.price_huf is not None:
        ref = search.reference_price_eur
        margin = ref - event.price_huf / rate
        pct = round(100 * abs(margin) / ref)
        sign = "+" if margin >= 0 else "−"
        lines.append(f"📈 resale ref {format_eur(ref)} → est. margin {sign}{format_eur(abs(margin))} ({sign}{pct}%)")

    where = " · ".join(p for p in (listing.location, SOURCE_LABELS.get(listing.source, listing.source)) if p)
    lines.append(f"📍 {esc(where)}")
    lines.append(f'<a href="{esc(listing.url, quote=True)}">Open listing</a>')
    return "\n".join(lines)


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))
