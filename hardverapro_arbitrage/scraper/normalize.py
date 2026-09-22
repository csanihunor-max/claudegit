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

# Real false negative this catches: "iPhone 12 128GB" and "iPhone 12 128
# GB" -- the exact same phone -- used to normalize to *different* keys
# ('iphone 12 128gb' vs 'iphone 12 128 gb') purely because one seller put
# a space before the unit and the other didn't. Checked against real
# scraped data: 4,709 observations collapsed to 4,565 distinct keys, and
# only 112 of those ever reached the 2-listing minimum needed to compute
# a reference price at all -- i.e. >97% of listings had zero comparables
# every cycle, no matter how the deal threshold was tuned. A unit written
# with or without a separating space is the single most common source of
# that split across capacity/frequency/wattage specs (GB, TB, HZ, W, ...),
# so numbers immediately followed by one of these unit words are merged
# into one token before the noise-word filter runs.
_UNIT_WORDS = {"gb", "tb", "mb", "hz", "ghz", "mhz", "mp", "wh", "w"}


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _merge_number_unit_tokens(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and tokens[i].isdigit() and tokens[i + 1] in _UNIT_WORDS:
            merged.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1
    return merged


def normalize_title(title: str) -> str:
    """Return a whitespace/case/accent/filler-word/unit-spacing-insensitive key.

    >>> normalize_title("Eladó iPhone 12 128GB, garanciával!")
    'iphone 12 128gb'
    >>> normalize_title("iphone 12 128 gb elado")
    'iphone 12 128gb'
    """
    text = _strip_accents(title).lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = _merge_number_unit_tokens(text.split())
    tokens = [tok for tok in tokens if tok not in _NOISE_WORDS]
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


# Real problem this catches: widening category coverage to every
# hardverapro.hu electronics category pulled in digital goods --
# subscription codes, game keys, software licenses -- mixed into
# otherwise-physical categories like "Xbox" or "PlayStation" (a "Game
# Pass Ultimate előfizetés" listing sits right next to an actual physical
# console). These aren't just noise, they're a category error: a digital
# code has no real used-market price (it's resold indefinitely at
# whatever the reseller sets, not worn down by use like a physical item),
# there's nothing to physically pick up (the distance-to-Budapest feature
# is meaningless for one), and mixing them in dilutes an already-wide
# category down to barely any genuinely comparable physical listings.
# Substrings, not a whole-key match like the bundle check above --
# these phrases can appear anywhere in an otherwise-normal-looking title.
_DIGITAL_GOOD_MARKERS = (
    "elofizet",  # "előfizetés"/"előfizetések" (subscription), any inflected form
    "game pass",
    "ps plus",
    "playstation plus",
    "xbox live",
    "digitalis kulcs",
    "digitalis kod",
    "steam kulcs",
    "licenc kulcs",
    "cd kulcs",
    "cd key",
    "azonnali kezbesit",  # "azonnali kézbesítés(sel)" -- instant delivery, meaningless for a physical item
    "feltoltokartya",
    "feltolto kartya",
)


def is_digital_good(normalized_key: str) -> bool:
    """True if this listing is a digital good (a subscription, game key,
    or software license) rather than a physical, pickupable item. See
    the comment above _DIGITAL_GOOD_MARKERS for why these need excluding
    outright rather than just letting them compete on price like a real
    used item.
    """
    return any(marker in normalized_key for marker in _DIGITAL_GOOD_MARKERS)
