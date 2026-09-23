"""Price parsing and currency helpers.

Hungarian sites write prices in many ways: "12 500 Ft", "12.500 Ft",
"12 500,- Ft", "12500Ft", "HUF 12 500", often with non-breaking or narrow
spaces as thousands separators. Non-numeric prices ("Megegyezés szerint",
"Ingyenes", "Alku") parse to None.
"""

from __future__ import annotations

import re

_SPACES = re.compile(r"[\s   ]+")
_CURRENCY_MARKERS = {
    "HUF": ("ft", "huf", "forint"),
    "EUR": ("€", "eur", "euro"),
}
_NUMBER = re.compile(r"\d[\d.,']*")


def parse_price(text: str | None, default_currency: str = "HUF") -> tuple[float, str] | None:
    """Parse a displayed price into (amount, currency). Returns None if there is no number."""
    if not text:
        return None
    lowered = text.lower()
    currency = default_currency
    for code, markers in _CURRENCY_MARKERS.items():
        if any(m in lowered for m in markers):
            currency = code
            break

    compact = _SPACES.sub("", lowered)
    compact = compact.replace(",-", "").replace(",—", "")
    match = _NUMBER.search(compact)
    if not match:
        return None
    amount = _parse_number(match.group(0).rstrip(".,"))
    if amount is None:
        return None
    return amount, currency


def _parse_number(raw: str) -> float | None:
    raw = raw.replace("'", "")
    if "," in raw and "." in raw:
        # Whichever separator comes last is the decimal mark: "1.234,50" / "1,234.50".
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        head, _, tail = raw.rpartition(sep)
        # Three digits after the last separator means thousands ("12.500", "1,250");
        # otherwise it is a decimal mark ("12 500,50 Ft", "12.5 EUR").
        if len(tail) == 3:
            raw = raw.replace(sep, "")
        else:
            raw = head.replace(sep, "") + "." + tail
    try:
        return float(raw)
    except ValueError:
        return None


def to_huf(amount: float | None, currency: str, eur_huf_rate: float) -> int | None:
    if amount is None:
        return None
    if currency == "HUF":
        return int(round(amount))
    if currency == "EUR":
        return int(round(amount * eur_huf_rate))
    return None


def huf_to_eur(amount_huf: float, eur_huf_rate: float) -> float:
    return amount_huf / eur_huf_rate


def format_huf(amount: float) -> str:
    """12500 -> '12 500 Ft' (space as thousands separator, as Hungarians write it)."""
    return f"{int(round(amount)):,}".replace(",", " ") + " Ft"


def format_eur(amount: float) -> str:
    return f"{amount:,.0f} €".replace(",", " ")
