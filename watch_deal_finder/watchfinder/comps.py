"""Links to comparable SOLD items, so a reference price can be checked against
what that model actually sold for.

Nothing here fetches anything: it builds eBay "sold items" search URLs that you
open in your own browser. The query is the listing's brand keyword plus the
words that identify the model (model names like "Copernicus", reference and
calibre numbers like "6309-7040" or "2609"), since "Raketa" alone mixes 5 €
spare parts with 200 € Copernicus pieces.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import quote_plus

from .filters import normalize

# Model names worth keeping in a sold-items search (normalized: lowercase, no accents).
MODEL_PHRASES = (
    # Soviet
    "big zero", "copernicus", "kopernikusz", "baltica", "amphibia", "amfibia", "komandirskie", "generalskie",
    "baltika", "tv tokos", "ufo", "albatros", "sturmanskie", "shturmanskie", "kirovskie", "de luxe", "aviator", "perpetual calendar",
    # Seiko
    "seiko 5", "bell matic", "lord matic", "lordmatic", "king seiko", "grand seiko", "sportsmatic", "actus",
    "presage", "turtle", "samurai", "monster", "pogue", "bullhead", "sea urchin", "kinetic",
    # Swiss
    "seamaster", "constellation", "de ville", "speedmaster", "geneve", "conquest", "flagship", "admiral",
    "visodate", "seastar", "pr 516", "sub 300", "le locle", "prx", "ds",
)
# Hungarian / alternative spellings -> the spelling eBay sellers use.
_ALIASES = {"kopernikusz": "copernicus", "baltika": "baltica", "tv tokos": "tv", "amfibia": "amphibia", "shturmanskie": "sturmanskie", "lordmatic": "lord matic"}
_YEAR = re.compile(r"^(19|20)\d\d$")
_MAX_TERMS = 4

# Kept out of the query even though they contain digits.
_NOT_A_REFERENCE = re.compile(r"^\d+(mm|m|ft|eur|k|db|cm|g|atm|bar)$")


def comps_query(title: str, keywords: Iterable[str]) -> str:
    """Build a short eBay search query identifying the model in a listing title."""
    norm = normalize(title)
    words = norm.split()
    padded = f" {norm} "
    terms: list[str] = []

    def add(parts: Iterable[str]) -> None:
        for p in parts:
            if p and p not in terms and len(terms) < _MAX_TERMS:
                terms.append(p)

    keywords = list(keywords)
    for kw in keywords:  # the search keyword that is actually in the title (the brand)
        parts = normalize(kw).split()
        if parts and all(any(w.startswith(p) for w in words) for p in parts):
            add(parts)
            break
    else:
        if keywords:
            add(normalize(keywords[0]).split())

    for phrase in MODEL_PHRASES:
        if f" {phrase} " in padded:
            add(_ALIASES.get(phrase, phrase).split())

    for w in words:  # reference / calibre numbers: 2609, 6309, 7s26, srpl87k1, pr516
        if any(c.isdigit() for c in w) and len(w) >= 3 and not _YEAR.match(w) and not _NOT_A_REFERENCE.match(w):
            add([w])
    return " ".join(terms)


def ebay_sold_url(query: str, domain: str = "ebay.de", category_ids: str | None = "31387") -> str:
    """eBay search limited to sold, completed listings."""
    url = f"https://www.{domain}/sch/i.html?_nkw={quote_plus(query)}&LH_Sold=1&LH_Complete=1"
    if category_ids:
        url += f"&_sacat={category_ids.split(',')[0]}"
    return url
