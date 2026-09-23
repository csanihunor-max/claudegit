from datetime import datetime, timezone

import hardverapro_arbitrage.web as web_module
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.storage import db
from hardverapro_arbitrage.web import create_app


def _listing(listing_id: str, price: float, location: str = "Budapest") -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://hardverapro.hu/x-t{listing_id}",
        title=f"Item {listing_id}",
        price=price,
        currency="HUF",
        location=location,
        seen_at=datetime.now(timezone.utc),
    )


def _deal(listing_id: str, price: float, reference: float, location: str = "Budapest") -> Deal:
    return Deal(
        listing=_listing(listing_id, price, location=location),
        market_reference_price=reference,
        discount_fraction=(reference - price) / reference,
        sample_size=3,
    )


def _make_client(tmp_path, deals, labels: dict | None = None):
    config = Config(search_urls=["https://example.com"], db_path=str(tmp_path / "test.sqlite3"))
    conn = db.connect(config.db_path)
    labels = labels or {}
    for deal in deals:
        # Mirrors real pipeline usage (pipeline.py always records an
        # observation for a listing before evaluating/recording it as a
        # deal) -- the dashboard now requires a fresh observation too (see
        # get_recent_deals' max_listing_age_seconds), so a deal with none
        # would wrongly look like a stale/jegelve listing under test.
        db.record_observation(conn, deal.listing)
        db.record_deal(conn, deal, source_label=labels.get(deal.listing.listing_id))
    conn.close()
    return create_app(config).test_client()


def test_dashboard_lists_deals_best_first(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),  # 20% off
            _deal("2", price=50_000, reference=100_000),  # 50% off
        ],
    )
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    # the 50%-off item must render before the 20%-off one
    assert body.index("Item 2") < body.index("Item 1")


def test_dashboard_empty_state(tmp_path):
    client = _make_client(tmp_path, [])
    response = client.get("/")
    assert response.status_code == 200
    assert "No deals detected yet" in response.get_data(as_text=True)


def test_api_deals_json(tmp_path):
    client = _make_client(tmp_path, [_deal("1", price=80_000, reference=100_000)])
    response = client.get("/api/deals")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]["listing_id"] == "1"
    assert payload[0]["discount_fraction"] == 0.2


def test_healthz(tmp_path):
    client = _make_client(tmp_path, [])
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_dashboard_shows_discount(tmp_path):
    client = _make_client(tmp_path, [_deal("1", price=80_000, reference=100_000)])
    body = client.get("/").get_data(as_text=True)
    assert "20%" in body


def test_dashboard_shows_sample_size(tmp_path):
    # Confidence signal already computed by the detector but previously
    # never surfaced -- a 2-sample "market reference" is just an average
    # of two prices, and the user has no way to judge that from the
    # dashboard alone without this.
    client = _make_client(tmp_path, [_deal("1", price=80_000, reference=100_000)])
    body = client.get("/").get_data(as_text=True)
    assert ">3<" in body


def test_sort_by_samples(tmp_path):
    config = Config(search_urls=["https://example.com"], db_path=str(tmp_path / "test.sqlite3"))
    conn = db.connect(config.db_path)
    low = Deal(listing=_listing("low", 80_000), market_reference_price=100_000, discount_fraction=0.2, sample_size=2)
    high = Deal(listing=_listing("high", 80_000), market_reference_price=100_000, discount_fraction=0.2, sample_size=9)
    for deal in (low, high):
        db.record_observation(conn, deal.listing)
        db.record_deal(conn, deal)
    conn.close()
    client = create_app(config).test_client()

    body = client.get("/?sort=samples").get_data(as_text=True)
    assert body.index("Item high") < body.index("Item low")


def test_sort_by_price_ascending_by_default(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),
            _deal("2", price=30_000, reference=100_000),
        ],
    )
    body = client.get("/?sort=price").get_data(as_text=True)
    # cheapest first is the sensible default for price, unlike discount
    assert body.index("Item 2") < body.index("Item 1")


def test_sort_direction_can_be_flipped(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),
            _deal("2", price=30_000, reference=100_000),
        ],
    )
    body = client.get("/?sort=price&dir=desc").get_data(as_text=True)
    assert body.index("Item 1") < body.index("Item 2")


def test_sort_by_category(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),
            _deal("2", price=80_000, reference=100_000),
        ],
        labels={"1": "Zebra Category", "2": "Alpha Category"},
    )
    body = client.get("/?sort=category").get_data(as_text=True)
    assert body.index("Item 2") < body.index("Item 1")  # Alpha before Zebra


def test_filter_by_category(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),
            _deal("2", price=80_000, reference=100_000),
        ],
        labels={"1": "Phones", "2": "Laptops"},
    )
    response = client.get("/?category=Phones")
    body = response.get_data(as_text=True)
    assert "Item 1" in body
    assert "Item 2" not in body


def test_api_deals_respects_sort_and_category_params(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),  # 20% off
            _deal("2", price=30_000, reference=100_000),  # 70% off
        ],
        labels={"1": "Phones", "2": "Phones"},
    )
    response = client.get("/api/deals?sort=price&dir=asc")
    payload = response.get_json()
    assert [d["listing_id"] for d in payload] == ["2", "1"]

    response = client.get("/api/deals?category=Nonexistent")
    assert response.get_json() == []


def test_api_deals_includes_distance_and_region(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000, location="Budapest"),
            _deal("2", price=80_000, reference=100_000, location="Gödöllő"),
            _deal("3", price=80_000, reference=100_000, location="Miskolc"),
            _deal("4", price=80_000, reference=100_000, location="Nowheresville"),
        ],
    )
    by_id = {d["listing_id"]: d for d in client.get("/api/deals").get_json()}
    assert by_id["1"]["region"] == "Budapest"
    assert by_id["1"]["distance_km"] == 0.0
    assert by_id["2"]["region"] == "Pest county"
    assert by_id["3"]["region"] == "Other"
    assert by_id["3"]["distance_km"] > 100
    assert by_id["4"]["region"] is None
    assert by_id["4"]["distance_km"] is None


def test_sort_by_distance_puts_unknown_last_regardless_of_direction(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("far", price=80_000, reference=100_000, location="Miskolc"),
            _deal("near", price=80_000, reference=100_000, location="Budapest"),
            _deal("unknown", price=80_000, reference=100_000, location="Nowheresville"),
        ],
    )
    nearest_first = client.get("/api/deals?sort=distance&dir=asc").get_json()
    assert [d["listing_id"] for d in nearest_first] == ["near", "far", "unknown"]

    farthest_first = client.get("/api/deals?sort=distance&dir=desc").get_json()
    assert [d["listing_id"] for d in farthest_first] == ["far", "near", "unknown"]


def test_invalid_sort_param_falls_back_to_default(tmp_path):
    client = _make_client(
        tmp_path,
        [
            _deal("1", price=80_000, reference=100_000),  # 20% off
            _deal("2", price=50_000, reference=100_000),  # 50% off
        ],
    )
    body = client.get("/?sort=not-a-real-column").get_data(as_text=True)
    assert body.index("Item 2") < body.index("Item 1")  # still discount desc


def test_refresh_runs_pipeline_and_redirects(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(web_module, "run_once", lambda *a, **kw: calls.append(a) or [])

    client = _make_client(tmp_path, [])
    response = client.post("/refresh")

    assert len(calls) == 1
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_refresh_without_search_urls_shows_error(tmp_path):
    config = Config(search_urls=[], db_path=str(tmp_path / "test.sqlite3"))
    db.connect(config.db_path).close()
    client = create_app(config).test_client()

    response = client.post("/refresh")

    assert response.status_code == 200  # renders the dashboard with an error, doesn't redirect
    assert "HA_SEARCH_URLS" in response.get_data(as_text=True)


def _ram_client(tmp_path, listings_with_labels: list[tuple[Listing, str | None]]):
    config = Config(search_urls=["https://example.com"], db_path=str(tmp_path / "ram.sqlite3"))
    conn = db.connect(config.db_path)
    for listing, source_label in listings_with_labels:
        db.record_observation(conn, listing, source_label=source_label)
    conn.close()
    return create_app(config).test_client()


def _ram_listing(listing_id: str, title: str, price: float, location: str = "Budapest") -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://hardverapro.hu/x-t{listing_id}",
        title=title,
        price=price,
        currency="HUF",
        location=location,
        seen_at=datetime.now(timezone.utc),
    )


def test_ram_finder_matches_only_ram_category_and_spec(tmp_path):
    client = _ram_client(
        tmp_path,
        [
            (_ram_listing("1", "G.SKILL Ripjaws V 32GB (2x16GB) DDR4 3200MHz CL16", 35_000), "RAM"),
            # too small a kit -- doesn't meet the 32GB floor
            (_ram_listing("2", "Kingston DDR4 8GB asztali RAM 2400MHz", 8_000), "RAM"),
            # a laptop whose *embedded* RAM happens to match the same spec --
            # must not appear just because the words match; it's not a RAM
            # listing, it's scraped from a different category entirely.
            (_ram_listing("3", "Gamer laptop i7 32GB DDR4 3200MHz RTX 4060 1TB SSD", 450_000), "Laptops"),
        ],
    )
    response = client.get("/ram?type=ddr4&min_capacity_gb=32&min_freq_mhz=3200")
    body = response.get_data(as_text=True)
    assert "G.SKILL" in body
    assert "Kingston" not in body
    assert "Gamer laptop" not in body


def test_ram_finder_sorts_by_price_ascending(tmp_path):
    client = _ram_client(
        tmp_path,
        [
            (_ram_listing("expensive", "Corsair Vengeance 32GB (2x16GB) DDR4 3600MHz", 50_000), "RAM"),
            (_ram_listing("cheap", "G.SKILL Ripjaws V 32GB (2x16GB) DDR4 3200MHz", 30_000), "RAM"),
        ],
    )
    body = client.get("/ram").get_data(as_text=True)
    assert body.index("G.SKILL") < body.index("Corsair")


def test_ram_finder_defaults_to_the_requested_spec(tmp_path):
    # No query params at all -- the whole point of "a dedicated button"
    # is that these defaults are exactly what was asked for.
    client = _ram_client(
        tmp_path,
        [(_ram_listing("1", "G.SKILL Ripjaws V 32GB (2x16GB) DDR4 3200MHz CL16", 35_000), "RAM")],
    )
    body = client.get("/ram").get_data(as_text=True)
    assert "G.SKILL" in body


def test_dashboard_links_to_ram_finder(tmp_path):
    client = _make_client(tmp_path, [])
    body = client.get("/").get_data(as_text=True)
    assert 'href="/ram' in body


def test_dashboard_links_to_gpu_finder(tmp_path):
    client = _make_client(tmp_path, [])
    body = client.get("/").get_data(as_text=True)
    assert 'href="/gpu' in body


def test_gpu_finder_matches_only_graphics_card_category_and_chip(tmp_path):
    client = _ram_client(
        tmp_path,
        [
            (_ram_listing("1", "GIGABYTE RTX 3070 Ti 8GB GDDR6X GAMING OC videokártya", 130_000), "Graphics Cards"),
            (_ram_listing("2", "SAPPHIRE Radeon RX570 4GB NITRO+ videokártya", 25_000), "Graphics Cards"),
            # a laptop whose embedded GPU happens to match the same chip --
            # must not appear, it's scraped from a different category.
            (_ram_listing("3", "ACER PREDATOR HELIOS 300 i7 RTX 3070 8GB laptop", 400_000), "Laptops"),
        ],
    )
    response = client.get("/gpu?chip=3070")
    body = response.get_data(as_text=True)
    assert "GIGABYTE" in body
    assert "RX570" not in body
    assert "PREDATOR" not in body


def test_gpu_finder_sorts_by_price_ascending(tmp_path):
    client = _ram_client(
        tmp_path,
        [
            (_ram_listing("expensive", "ASUS RTX 3070 Ti 8GB videokártya", 140_000), "Graphics Cards"),
            (_ram_listing("cheap", "GIGABYTE RTX 3070 8GB videokártya", 100_000), "Graphics Cards"),
        ],
    )
    body = client.get("/gpu").get_data(as_text=True)
    assert body.index("GIGABYTE") < body.index("ASUS")


def test_gpu_finder_filters_by_min_vram(tmp_path):
    client = _ram_client(
        tmp_path,
        [
            (_ram_listing("1", "BIOSTAR GeForce GT 1030 4GB videokártya", 15_000), "Graphics Cards"),
            (_ram_listing("2", "SAPPHIRE RX 7900 XTX Nitro+ 24GB videokártya", 500_000), "Graphics Cards"),
        ],
    )
    body = client.get("/gpu?min_vram_gb=16").get_data(as_text=True)
    assert "SAPPHIRE" in body
    assert "BIOSTAR" not in body


def test_refresh_failure_is_caught_and_shown(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(web_module, "run_once", boom)
    client = _make_client(tmp_path, [])

    response = client.post("/refresh")

    assert response.status_code == 200
    assert "Refresh failed" in response.get_data(as_text=True)
