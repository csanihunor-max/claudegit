"""Jófogás (www.jofogas.hu) search results.

What the site looks like (checked 2026-09-23):
- Next.js, server-side rendered. Every search page embeds the full result set
  as JSON in <script id="__NEXT_DATA__">, under props.pageProps.adList.ads,
  so plain requests + BeautifulSoup is enough (no JavaScript / Playwright).
- 36 ads per page, newest first (a few paid "kiemelt" ads are pinned on top).
- Category-scoped search: /magyarorszag/<category-slug>?q=<keyword>.
  "karorak-" = Férfi > Karórák (men's watches), "karorak" = Női > Karórák.
- robots.txt allows /magyarorszag/...?q=... but disallows price filters
  (min_price / max_price), `&o=` pagination and several sort parameters,
  so we fetch page 1 only and apply max price ourselves.
- A removed ad's page returns HTTP 410.
- The default python-requests User-Agent gets HTTP 429 from their CDN; the
  honest "compatible; WatchDealFinder/1.0" one is served normally.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..config import JofogasConfig, SearchConfig
from ..http import HttpClient, HttpError
from ..models import Listing, SearchResult
from ..pricing import parse_price
from .base import Source, SourceError

log = logging.getLogger(__name__)

BASE_URL = "https://www.jofogas.hu"


def search_url(keyword: str, category: str = "") -> str:
    path = "/magyarorszag" + (f"/{category.strip('/')}" if category.strip("/") else "")
    return f"{BASE_URL}{path}?q={quote(keyword.strip())}"


def parse_search_page(html: str) -> SearchResult:
    """Parse one search result page. Raises SourceError if the page isn't what we expect."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise SourceError("Jófogás page has no __NEXT_DATA__ block (markup changed or not a search page)")
    try:
        data = json.loads(script.string)
        ad_list = data["props"]["pageProps"]["adList"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError(f"Jófogás __NEXT_DATA__ has no adList ({exc!r})") from exc

    ads = ad_list.get("ads") or []
    listings = [listing for ad in ads if (listing := _parse_ad(ad)) is not None]

    pager = ad_list.get("pager") or {}
    total = ad_list.get("search_total")
    if pager.get("page_count") is not None:
        complete = int(pager["page_count"]) <= 1
    elif total is not None:
        complete = int(total) <= len(ads)
    else:
        complete = not ads
    return SearchResult(listings=listings, complete=complete)


def _parse_ad(ad: dict[str, Any]) -> Listing | None:
    list_id = ad.get("list_id")
    title = (ad.get("subject") or "").strip()
    url = ad.get("url")
    if not list_id or not title or not url:
        return None

    price_info = ad.get("price") or {}
    price: float | None = None
    if isinstance(price_info.get("value"), (int, float)) and price_info["value"] > 0:
        price = float(price_info["value"])
    else:
        parsed = parse_price(price_info.get("label"))
        price = parsed[0] if parsed else None

    return Listing(
        source="jofogas",
        listing_id=str(list_id),
        title=title,
        price=price,
        currency="HUF",
        url=url,
        location=_location(ad),
        thumbnail_url=_thumbnail(ad),
        category=" > ".join(c.get("name", "") for c in ad.get("category_tree") or []) or None,
        details=_text(ad.get("body")),
    )


def _text(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)[:4000] or None


def _location(ad: dict[str, Any]) -> str | None:
    city = None
    for param in ad.get("parameters") or []:
        if param.get("key") == "city" and param.get("values"):
            city = param["values"][0].get("label")
    region = (ad.get("region") or {}).get("label")
    parts = [p for p in (city, region) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return ", ".join(parts) or None


def _thumbnail(ad: dict[str, Any]) -> str | None:
    images = ad.get("images") or []
    if not images:
        return None
    first = images[0]
    for variant in first.get("image_size_variations") or []:
        if variant.get("type") == "bigthumbs" and variant.get("url"):
            return variant["url"]
    return first.get("url")


class JofogasSource(Source):
    name = "jofogas"
    label = "Jófogás"

    def __init__(self, http: HttpClient, config: JofogasConfig):
        self.http = http
        self.config = config

    def search(self, search: SearchConfig) -> SearchResult:
        seen: dict[str, Listing] = {}
        complete = True
        for keyword in search.keywords:
            for category in self.config.categories or ("",):
                url = search_url(keyword, category)
                try:
                    resp = self.http.get(url)
                except HttpError as exc:
                    raise SourceError(str(exc)) from exc
                if resp.status_code != 200:
                    raise SourceError(f"GET {url} returned HTTP {resp.status_code}")
                page = parse_search_page(resp.text)
                log.debug("jofogas %r in %r: %d ads (complete=%s)", keyword, category, len(page.listings), page.complete)
                complete = complete and page.complete
                for listing in page.listings:
                    seen.setdefault(listing.listing_id, listing)
        return SearchResult(listings=list(seen.values()), complete=complete)

    def is_gone(self, listing: Listing) -> bool | None:
        try:
            resp = self.http.get(listing.url, allow_redirects=False)
        except HttpError as exc:
            log.info("could not check %s: %s", listing.url, exc)
            return None
        if resp.status_code in (404, 410):
            return True
        if resp.status_code == 200:
            return False
        return None
