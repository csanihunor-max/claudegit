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


def test_refresh_failure_is_caught_and_shown(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(web_module, "run_once", boom)
    client = _make_client(tmp_path, [])

    response = client.post("/refresh")

    assert response.status_code == 200
    assert "Refresh failed" in response.get_data(as_text=True)
