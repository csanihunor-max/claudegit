import pytest

from watchfinder.pricing import format_eur, format_huf, parse_price, to_huf


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12 500 Ft", (12500, "HUF")),
        ("12 500 Ft", (12500, "HUF")),          # non-breaking space
        ("12 500 Ft", (12500, "HUF")),     # narrow no-break space
        ("12.500 Ft", (12500, "HUF")),
        ("12 500,- Ft", (12500, "HUF")),
        ("12.500,-Ft", (12500, "HUF")),
        ("12500Ft", (12500, "HUF")),
        ("1 250 000 Ft", (1250000, "HUF")),
        ("1.250.000 Ft", (1250000, "HUF")),
        ("Ár: 8 990 Ft", (8990, "HUF")),
        ("HUF 45 000", (45000, "HUF")),
        ("45 000 forint", (45000, "HUF")),
        ("300 Ft", (300, "HUF")),
        ("12 500,50 Ft", (12500.5, "HUF")),
        ("€ 129,99", (129.99, "EUR")),
        ("1.234,50 EUR", (1234.5, "EUR")),
        ("89.90 EUR", (89.9, "EUR")),
        ("15 000", (15000, "HUF")),                  # no currency: default HUF
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", [None, "", "Megegyezés szerint", "Ingyenes", "Alku", "Ft"])
def test_parse_price_non_numeric(text):
    assert parse_price(text) is None


def test_to_huf():
    assert to_huf(12500, "HUF", 400) == 12500
    assert to_huf(100.0, "EUR", 395.5) == 39550
    assert to_huf(None, "HUF", 400) is None
    assert to_huf(10, "GBP", 400) is None


def test_formatting():
    assert format_huf(12500) == "12 500 Ft"
    assert format_huf(1250000) == "1 250 000 Ft"
    assert format_eur(31.25) == "31 €"
