"""Turn a free-text listing title into a stable key for grouping the same
item across many listings, so prices are only ever compared apples-to-apples.

This is intentionally conservative: it strips common Hungarian marketplace
filler words and punctuation/whitespace noise, but does NOT try to parse
brand/model out of the title, because getting that wrong silently merges
different products into one price bucket. Two listings only compare as
"the same item" if their titles reduce to an identical key.
"""
from __future__ import annotations

import re
import unicodedata

# Words that describe the *sale*, not the *product*, common on Hungarian
# classifieds. Stripping these lets "iPhone 12 128GB eladó" and "Eladó
# iPhone 12 128GB garanciával" normalize to the same key.
_NOISE_WORDS = {
    "elado",
    "elad",
    "csere",
    "csereberelnek",
    "garancia",
    "garanciaval",
    "szamlaval",
    "szamlazoval",
    "uj",
    "ujszeru",
    "hasznalt",
    "bontatlan",
    "bontott",
    "sürgős",
    "surgos",
    "akcio",
    "olcson",
    "ritkasag",
    "kiváló",
    "kivalo",
    "állapotban",
    "allapotban",
}

_PUNCT_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(title: str) -> str:
    """Return a whitespace/case/accent/filler-word-insensitive key.

    >>> normalize_title("Eladó iPhone 12 128GB, garanciával!")
    'iphone 12 128gb'
    >>> normalize_title("iphone 12 128 gb elado")
    'iphone 12 128 gb'
    """
    text = _strip_accents(title).lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = [tok for tok in text.split() if tok not in _NOISE_WORDS]
    return _WHITESPACE_RE.sub(" ", " ".join(tokens)).strip()


# Real false positives this catches: "PS4 játékok" ("PS4 games"), "Xbox
# one játékok", "Nintendo Switch Játékok", "PC játékok" all normalize to
# a clean-looking key, but each one is a seller's own lot of however many
# games they happened to bundle -- not one product independently priced
# by different sellers. The `max_group_spread_ratio` price-spread guard
# (pricing/market.py) sometimes catches these after the fact, but only
# when the specific bundles it saw happened to disagree enough in price;
# it missed several real instances of exactly this pattern. This targets
# the actual cause instead: a key that reduces to just "<platform> games"
# with nothing else naming a specific title, or that contains an explicit
# lot/bundle word, was never one comparable product to begin with.
_BUNDLE_SIGNAL_WORDS = {"csomag", "tetel", "tetelben", "gyujtemeny", "vegyes", "leltar"}

_PLATFORM_ALTERNATION = (
    r"(playstation( ?[2345])?|ps[2345]|psx|ps vita|"
    r"nintendo( switch( 2| oled| lite)?)?|switch|"
    r"xbox( one| 360| series [xs])?|wii( u)?|3ds|nds|ds|pc)"
)
_GENERIC_GAMES_RE = re.compile(rf"^{_PLATFORM_ALTERNATION} jatek(ok)?$")


def is_bundle_or_generic_key(normalized_key: str) -> bool:
    """True if this normalized key can't safely be treated as one
    comparable product: either it names an explicit lot/bundle of several
    items, or it's nothing more specific than a platform name plus the
    bare word "games" (see module docstring above for the real false
    positives this is built from).
    """
    if set(normalized_key.split()) & _BUNDLE_SIGNAL_WORDS:
        return True
    return bool(_GENERIC_GAMES_RE.match(normalized_key))
