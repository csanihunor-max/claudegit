from datetime import datetime, timezone

from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.notify.console import format_deal


def _listing() -> Listing:
    return Listing(
        listing_id="1", url="https://hardverapro.hu/x-t1", title="Steam Deck OLED 512GB",
        price=200_000, currency="HUF", location="Budapest", seen_at=datetime.now(timezone.utc),
    )


def test_format_used_median_deal():
    deal = Deal(listing=_listing(), basis="used_median", market_reference_price=250_000, discount_fraction=0.2, sample_size=4)
    text = format_deal(deal)
    assert "250,000" in text
    assert "20%" in text
    assert "save" in text.lower()


def test_format_retail_deal_does_not_touch_none_fields():
    # this is the exact shape that used to crash format_deal: used-median
    # fields are None on a retail-basis deal.
    deal = Deal(
        listing=_listing(), basis="retail",
        retail_reference_price=400_000, retail_discount_fraction=0.5, retail_match_confidence=0.85,
    )
    text = format_deal(deal)
    assert "400,000" in text
    assert "50%" in text
    assert "85%" in text
