"""eBay via the official Browse API (no scraping).

Needs a Production keyset from developer.ebay.com (EBAY_CLIENT_ID /
EBAY_CLIENT_SECRET in .env). Uses the client-credentials OAuth flow, which
only grants read access to public listing data. Mainly meant for comparing
against active eBay prices: the dashboard shows the eBay median per search,
and eBay alerts are off unless `sources.ebay.notify` is true.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from ..config import EbayConfig, SearchConfig
from ..http import HttpClient, HttpError
from ..models import Listing, SearchResult
from .base import Source, SourceError

log = logging.getLogger(__name__)

API = "https://api.ebay.com"
TOKEN_URL = f"{API}/identity/v1/oauth2/token"
SEARCH_URL = f"{API}/buy/browse/v1/item_summary/search"
ITEM_URL = f"{API}/buy/browse/v1/item/"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def parse_search_response(data: dict[str, Any]) -> SearchResult:
    items = data.get("itemSummaries") or []
    listings = [listing for item in items if (listing := _parse_item(item)) is not None]
    total = data.get("total")
    complete = total is not None and int(total) <= len(items)
    return SearchResult(listings=listings, complete=complete)


def _parse_item(item: dict[str, Any]) -> Listing | None:
    item_id, title, url = item.get("itemId"), item.get("title"), item.get("itemWebUrl")
    if not item_id or not title or not url:
        return None
    price_info = item.get("price") or item.get("currentBidPrice") or {}
    try:
        price = float(price_info["value"])
        currency = str(price_info.get("currency") or "EUR")
    except (KeyError, TypeError, ValueError):
        price, currency = None, "EUR"
    image = (item.get("image") or {}).get("imageUrl")
    if not image and item.get("thumbnailImages"):
        image = item["thumbnailImages"][0].get("imageUrl")
    loc = item.get("itemLocation") or {}
    location = ", ".join(p for p in (loc.get("city"), loc.get("country")) if p) or None
    categories = item.get("categories") or []
    return Listing(
        source="ebay",
        listing_id=str(item_id),
        title=str(title).strip(),
        price=price,
        currency=currency,
        url=url,
        location=location,
        thumbnail_url=image,
        category=" > ".join(c.get("categoryName", "") for c in categories) or None,
    )


class EbaySource(Source):
    name = "ebay"
    label = "eBay"

    def __init__(
        self,
        http: HttpClient,
        config: EbayConfig,
        client_id: str,
        client_secret: str,
        clock: Callable[[], float] = time.time,
    ):
        self.http = http
        self.config = config
        self._auth = (client_id, client_secret)
        self._clock = clock
        self._token: str | None = None
        self._token_expires = 0.0

    def _get_token(self, force: bool = False) -> str:
        if not force and self._token and self._clock() < self._token_expires - 60:
            return self._token
        try:
            resp = self.http.post(
                TOKEN_URL,
                auth=self._auth,
                data={"grant_type": "client_credentials", "scope": SCOPE},
                check_robots=False,
            )
        except HttpError as exc:
            raise SourceError(f"eBay OAuth failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"eBay OAuth failed: HTTP {resp.status_code} {_error_text(resp)}")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = self._clock() + float(body.get("expires_in", 7200))
        return self._token

    def _api_get(self, url: str, params: dict[str, Any] | None = None):
        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {self._get_token(force=attempt > 0)}",
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace,
            }
            try:
                resp = self.http.get(url, params=params, headers=headers, check_robots=False)
            except HttpError as exc:
                raise SourceError(f"eBay API: {exc}") from exc
            if resp.status_code != 401:
                return resp
        return resp

    def search(self, search: SearchConfig) -> SearchResult:
        seen: dict[str, Listing] = {}
        complete = True
        for keyword in search.keywords:
            params: dict[str, Any] = {"q": keyword, "limit": self.config.limit, "sort": "newlyListed"}
            if self.config.category_ids:
                params["category_ids"] = self.config.category_ids
            resp = self._api_get(SEARCH_URL, params)
            if resp.status_code != 200:
                raise SourceError(f"eBay search {keyword!r}: HTTP {resp.status_code} {_error_text(resp)}")
            page = parse_search_response(resp.json())
            complete = complete and page.complete
            for listing in page.listings:
                seen.setdefault(listing.listing_id, listing)
        return SearchResult(listings=list(seen.values()), complete=complete)

    def is_gone(self, listing: Listing) -> bool | None:
        try:
            resp = self._api_get(ITEM_URL + listing.listing_id)
        except SourceError as exc:
            log.info("could not check eBay item %s: %s", listing.listing_id, exc)
            return None
        if resp.status_code == 404:
            return True
        if resp.status_code == 200:
            return False
        return None


def _error_text(resp) -> str:
    try:
        errors = resp.json().get("errors") or []
        if errors:
            return errors[0].get("message", "")
        return resp.json().get("error_description", "")
    except ValueError:
        return ""
