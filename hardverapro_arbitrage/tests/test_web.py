from datetime import datetime, timezone

import hardverapro_arbitrage.web as web_module
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.storage import db
from hardverapro_arbitrage.web import create_app


def _listing(listing_id: str, price: float) -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://hardverapro.hu/x-t{listing_id}",
        title=f"Item {listing_id}",
        price=price,
        currency="HUF",
        location="Budapest",
        seen_at=datetime.now(timezone.utc),
    )


def _deal(listing_id: str, price: float, reference: float) -> Deal:
    return Deal(
        listing=_listing(listing_id, price),
        basis="used_median",
        market_reference_price=reference,
        discount_fraction=(reference - price) / reference,
        sample_size=3,
    )


def _retail_only_deal(listing_id: str, price: float, retail_reference: float) -> Deal:
    return Deal(
        listing=_listing(listing_id, price),
        basis="retail",
        retail_reference_price=retail_reference,
        retail_discount_fraction=(retail_reference - price) / retail_reference,
        retail_match_confidence=0.9,
    )


def _make_client(tmp_path, deals):
    config = Config(search_urls=["https://example.com"], db_path=str(tmp_path / "test.sqlite3"))
    conn = db.connect(config.db_path)
    for deal in deals:
        # Mirrors real pipeline usage (pipeline.py always records an
        # observation for a listing before evaluating/recording it as a
        # deal) -- the dashboard now requires a fresh observation too (see
        # get_recent_deals' max_listing_age_seconds), so a deal with none
        # would wrongly look like a stale/jegelve listing under test.
        db.record_observation(conn, deal.listing)
        db.record_deal(conn, deal)
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


def test_dashboard_shows_secondhand_margin_when_available(tmp_path):
    client = _make_client(tmp_path, [_deal("1", price=80_000, reference=100_000)])
    body = client.get("/").get_data(as_text=True)
    assert "Margin vs secondhand" in body
    assert "20%" in body
    assert "not enough resale history yet" not in body


def test_dashboard_shows_missing_secondhand_history_for_retail_only_deal(tmp_path):
    client = _make_client(tmp_path, [_retail_only_deal("1", price=50_000, retail_reference=100_000)])
    body = client.get("/").get_data(as_text=True)
    assert "not enough resale history yet" in body


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
