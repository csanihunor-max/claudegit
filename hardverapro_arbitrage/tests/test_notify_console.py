from datetime import datetime, timezone

from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.notify.console import format_deal


def _listing() -> Listing:
    return Listing(
        listing_id="1", url="https://hardverapro.hu/x-t1", title="Steam Deck OLED 512GB",
        price=200_000, currency="HUF", location="Budapest", seen_at=datetime.now(timezone.utc),
    )


def test_format_deal():
    deal = Deal(listing=_listing(), market_reference_price=250_000, discount_fraction=0.2, sample_size=4)
    text = format_deal(deal)
    assert "250,000" in text
    assert "20%" in text
    assert "save" in text.lower()
