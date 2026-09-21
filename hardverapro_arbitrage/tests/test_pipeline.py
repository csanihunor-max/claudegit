from datetime import datetime, timezone

import hardverapro_arbitrage.pipeline as pipeline_module
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Listing
from hardverapro_arbitrage.notify.console import ConsoleNotifier
from hardverapro_arbitrage.storage import db


class _FakeHardveraproClient:
    def get(self, url: str) -> str:
        return "<html></html>"  # content ignored; parse_search_results is monkeypatched


def _listing(listing_id: str, price: float, title: str) -> Listing:
    return Listing(
        listing_id=listing_id, url=f"https://hardverapro.hu/x-t{listing_id}", title=title,
        price=price, currency="HUF", location=None, seen_at=datetime.now(timezone.utc),
    )


def test_bundle_or_generic_titles_never_flagged_as_deals(monkeypatch):
    # Real false positive this guards against: "PS4 játékok" ("PS4
    # games") listings are each a seller's own differently-sized bundle,
    # not one product -- even a huge apparent price gap here must never
    # produce a deal, and must never contaminate anyone else's reference
    # price either.
    listings = [
        _listing("1", 3_000, "PS4 játékok"),
        _listing("2", 4_500, "PS4 játékok"),
        _listing("3", 12_345, "PS4 játékok"),
    ]
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: listings)

    config = Config(search_urls=["https://example.com"], max_pages_per_category=1, deal_discount_threshold=0.01)
    conn = db.connect(":memory:")
    deals = pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert deals == []
    # still recorded for historical completeness, just never evaluated
    cur = conn.execute("SELECT COUNT(*) FROM observations")
    assert cur.fetchone()[0] == 3


def test_offset_url_builds_correctly():
    assert pipeline_module._offset_url("https://x.hu/index.html", 0) == "https://x.hu/index.html"
    assert pipeline_module._offset_url("https://x.hu/index.html", 100) == "https://x.hu/index.html?offset=100"
    assert pipeline_module._offset_url("https://x.hu/index.html?a=1", 100) == "https://x.hu/index.html?a=1&offset=100"


class _PagedFakeClient:
    """Returns a distinct dummy html string per page, so a monkeypatched
    parse_search_results can tell pages apart by url/offset without
    needing real HTML.
    """

    def __init__(self):
        self.urls_fetched: list[str] = []

    def get(self, url: str) -> str:
        self.urls_fetched.append(url)
        return url  # parse_search_results below is monkeypatched to treat this as the page url


def test_pagination_stops_when_a_page_returns_no_listings(monkeypatch):
    client = _PagedFakeClient()

    def fake_parse(html):
        # html here IS the url, per _PagedFakeClient.get above
        if "offset=" not in html:
            return [_listing("1", 10_000, "Item 1")]
        return []  # page 2 (offset=100) is empty -- end of category

    monkeypatch.setattr(pipeline_module, "parse_search_results", fake_parse)

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=5)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    # page 1 had a listing (kept going), page 2 was empty (stopped there, never tried a 3rd)
    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
    ]


def test_pagination_respects_max_pages_cap(monkeypatch):
    client = _PagedFakeClient()
    # every page has a genuinely NEW listing -- pagination would run
    # forever without the cap, since it would never see "no new listings"
    monkeypatch.setattr(
        pipeline_module,
        "parse_search_results",
        lambda html: [_listing(html, 10_000, "Item")],  # html is the page url here, so each page's id is unique
    )

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=3)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
        "https://example.com/index.html?offset=200",
    ]


def test_pagination_stops_on_wraparound_not_just_empty_pages(monkeypatch):
    # The real bug this guards against: a category smaller than one page
    # doesn't get an empty result past its end -- the site wraps around
    # and re-serves page 1's exact listings instead (verified against a
    # real fetch). "0 listings" never fires as a stop condition there;
    # only "0 *new* listings" does.
    client = _PagedFakeClient()
    same_listing = _listing("1", 10_000, "Item 1")
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: [same_listing])

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=5)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    # page 1: listing "1" is new, kept going. page 2: same listing "1"
    # again -- 0 new, stop. Never reaches page 3, 4, or 5.
    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
    ]

    # and it was only recorded once, not once per page fetched
    cur = conn.execute("SELECT COUNT(*) FROM observations")
    assert cur.fetchone()[0] == 1
