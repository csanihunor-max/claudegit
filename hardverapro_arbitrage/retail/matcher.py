"""Match a hardverapro.hu listing to the right product on a retail
price-comparison site, with a confidence score — never a guess presented
as certain.

Cross-site title matching is fundamentally fuzzier than the same-site
exact-key matching `scraper/normalize.py` does for grouping hardverapro
listings against each other: a resale ad's title ("Steam Deck OLED
512GB BONTATLAN") and a retail listing's title ("Valve Steam Deck OLED
512 GB kézikonzol") describe the same product in different vocabularies.
This scores candidates instead of requiring exact equality, and a low
score means "don't compare against this" rather than "compare loosely" —
a wrong match would silently produce a wrong price comparison, which is
worse than no comparison at all in a tool about money.
"""
from __future__ import annotations

import re

from ..models import RetailPrice
from ..scraper.normalize import normalize_title

# Retail sites format specs with a space ("512 GB"); resale ad titles often
# don't ("512GB"). Collapse both to the same token so the single strongest
# identity signal for consumer electronics (capacity, model number) isn't
# lost to formatting differences. This is separate from (and doesn't
# change) normalize_title's own behavior, which other code relies on.
_UNIT_JOIN_RE = re.compile(r"\b(\d+)\s+(gb|tb|mb|mp|hz|w|mah|k)\b")


def _match_tokens(text: str) -> set[str]:
    joined = _UNIT_JOIN_RE.sub(r"\1\2", normalize_title(text))
    return {tok for tok in joined.split() if tok}


def _is_spec_token(token: str) -> bool:
    """A token that names a concrete spec (a capacity, a model number) —
    the strongest identity signal, as opposed to a generic word shared by
    many different products ("gaming", "asus", "fekete" / "black").
    """
    return any(ch.isdigit() for ch in token)


def score_match(listing_title: str, candidate_title: str) -> float:
    """0..1: how confident a match this candidate is for this listing.

    Containment of the LISTING's tokens in the candidate (not overlap of
    the union) — a retail title is typically longer and more formal, so
    it should be expected to be a superset of the ad's own words. Zero
    shared spec tokens when the listing has some heavily penalizes the
    score: word overlap alone ("asus", "gaming") without a matching
    capacity or model number is exactly the case likely to be a
    different variant of the same product line.
    """
    listing_tokens = _match_tokens(listing_title)
    if not listing_tokens:
        return 0.0
    candidate_tokens = _match_tokens(candidate_title)

    shared = listing_tokens & candidate_tokens
    if not shared:
        return 0.0

    containment = len(shared) / len(listing_tokens)

    listing_specs = {t for t in listing_tokens if _is_spec_token(t)}
    shared_specs = {t for t in shared if _is_spec_token(t)}
    if listing_specs and not shared_specs:
        containment *= 0.3

    return min(containment, 1.0)


def best_match(
    listing_title: str, candidates: list[tuple[str, float, str, str]]
) -> RetailPrice | None:
    """Pick the best-scoring candidate. Each candidate is
    (product_title, price, currency, url). Returns None only when there
    are no candidates at all — a low-confidence best match is still
    returned, with its score, so the CALLER (see arbitrage/detector.py,
    gated on config.retail_min_match_confidence) decides whether to trust
    it. That keeps the accept/reject threshold in one configurable place
    instead of duplicated here.
    """
    if not candidates:
        return None

    scored = [(score_match(listing_title, title), title, price, currency, url) for title, price, currency, url in candidates]
    scored.sort(key=lambda t: t[0], reverse=True)
    score, title, price, currency, url = scored[0]

    return RetailPrice(
        product_title=title,
        price=price,
        currency=currency,
        url=url,
        match_confidence=score,
    )
