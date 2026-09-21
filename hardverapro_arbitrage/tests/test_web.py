from datetime import datetime, timezone

from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.storage import db
from hardverapro_arbitrage.web import create_app


def _deal(listing_id: str, price: float, reference: float) -> Deal:
    listing = Listing(
        listing_id=listing_id,
        url=f"https://hardverapro.hu/x-t{listing_id}",
        title=f"Item {listing_id}",
        price=price,
        currency="HUF",
        location="Budapest",
        seen_at=datetime.now(timezone.utc),
    )
    return Deal(
        listing=listing,
        market_reference_price=reference,
        discount_fraction=(reference - price) / reference,
        sample_size=3,
    )


def _make_client(tmp_path, deals):
    config = Config(search_urls=["https://example.com"], db_path=str(tmp_path / "test.sqlite3"))
    conn = db.connect(config.db_path)
    for deal in deals:
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
