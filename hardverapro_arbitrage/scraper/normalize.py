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
