"""What model a listing is, for grouping comparable listings and for links to
comparable SOLD items.

`model_signature` reads a title into: the brand keyword, model names
("Copernicus", "Seamaster"), reference / calibre numbers ("6309-7040", "2609"),
and attributes that change the price a lot (ladies' size, solid gold,
automatic vs quartz). From that it builds:

- `query`: the eBay search for sold items of this model (a link you open in the
  browser; nothing here fetches anything), and
- `group_keys`: keys for grouping comparable listings, most specific first. A
  listing never falls back to a key coarser than its model: a Raketa
  Copernicus is compared with Copernicuses, never with "all Raketas"; only a
  title with no model words at all lands in the brand-only group, next to other
  equally vague titles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus

from .filters import normalize

# Model names (normalized: lowercase, no accents). Longer phrases first where one contains another.
MODEL_PHRASES = (
    # Soviet
    "big zero", "copernicus", "kopernikusz", "baltica", "baltika", "perpetual calendar", "orokkaptaras",
    "oroknaptaras", "tv tokos", "ufo", "polar", "leningrad", "amphibia", "amfibia", "komandirskie",
    "generalskie", "ministry", "neptune", "europe", "partner", "albatros", "sturmanskie", "shturmanskie", "kirovskie", "okean",
    "aviator", "de luxe", "signal", "transistor", "zim",
    # Seiko
    "seiko 5", "bell matic", "lord matic", "lordmatic", "king seiko", "grand seiko", "sportsmatic", "actus",
    "presage", "prospex", "alpinist", "cocktail time", "turtle", "samurai", "monster", "pogue", "bullhead",
    "sea urchin", "kinetic", "skx",
    # Swiss
    "seamaster", "cosmic", "constellation", "de ville", "speedmaster", "geneve", "ladymatic", "conquest", "hydroconquest",
    "flagship", "admiral", "presence", "dolce vita", "heritage", "master collection", "record", "spirit",
    "visodate", "seastar", "pr 516", "pr 100", "prx", "le locle", "t race", "couturier", "gentleman",
    "jumbo", "sub 300", "sub 200", "ds action", "ds podium", "ds 1", "ds", "blue ribbon",
)
# Hungarian / alternative spellings -> the spelling eBay sellers use.
_ALIASES = {
    "kopernikusz": "copernicus", "baltika": "baltica", "tv tokos": "tv", "amfibia": "amphibia",
    "shturmanskie": "sturmanskie", "lordmatic": "lord matic", "orokkaptaras": "perpetual calendar",
    "oroknaptaras": "perpetual calendar",
}
# Attributes that split a model into different price classes. "strong" ones are
# never dropped when looking for a bigger comparison group; movement type is.
_LADY = re.compile(r"\b(noi|lady|ladies|hölgy|holgy)\b")
_GOLD = re.compile(r"\b(18k|14k|18 k|14 k|18kt|14kt|tomor arany|arany tok|solid gold|585|750)\b")
_GOLD_WORD = re.compile(r"\b(arany|aranyora)\b")  # gold / gold watch; "aranyozott" (gold-plated) doesn't match
# Vintage cues, used to split vague titles (no model words) into vintage vs modern.
_VINTAGE = re.compile(r"\b(szovjet|orosz|cccp|ussr|sssr|koves|retro|regi|antik|vintage|(19[2-9]\d)(\w*)|\d0 ?as evek\w*)\b")
_AUTOMATIC = re.compile(r"\b(automata|automatic|automatikus|automat)\b")
_QUARTZ = re.compile(r"\b(quartz|kvarc|elemes)\b")

_YEAR = re.compile(r"^(19|20)\d\d$")
# Kept out of the reference numbers even though they contain digits.
_NOT_A_REFERENCE = re.compile(r"^\d+(mm|m|ft|eur|k|kt|db|cm|g|atm|bar)$|^(585|750)$")
_MAX_REFS = 2


@dataclass(frozen=True)
class ModelSignature:
    brand: tuple[str, ...]
    models: tuple[str, ...]
    refs: tuple[str, ...]
    strong: tuple[str, ...]      # lady / gold
    movement: tuple[str, ...]    # automatic / quartz

    @property
    def market_ok(self) -> bool:
        """Whether this listing's groups are specific enough for an automatic market price.
        A vague modern title ("Vostok Anchar" when Anchar isn't a known model) is not: its
        brand-only group mixes everything from 7 000 to 500 000 Ft."""
        return bool(self.models or self.refs or "vintage" in self.strong)

    @property
    def query(self) -> str:
        # "vintage" only narrows an eBay search when nothing more specific is known.
        strong = self.strong if not (self.models or self.refs) else tuple(a for a in self.strong if a != "vintage")
        return " ".join(_dedupe(self.brand + self.models + self.refs + strong + self.movement))

    @property
    def group_keys(self) -> list[str]:
        b, m, r, s, mv = self.brand, self.models, self.refs, self.strong, self.movement
        if m:
            candidates = [b + m + r + s + mv, b + m + r + s, b + m + s + mv, b + m + s]
        elif r:  # identified only by a reference number: never widen past it
            candidates = [b + r + s + mv, b + r + s]
        else:    # a vague title: compare with other vague titles of the same kind
            candidates = [b + s + mv, b + s]
        keys: list[str] = []
        for c in candidates:
            key = " ".join(_dedupe(c))
            if key and key not in keys:
                keys.append(key)
        return keys


def _dedupe(parts: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return out


def model_signature(title: str, keywords: Iterable[str]) -> ModelSignature:
    norm = normalize(title)
    words = norm.split()
    padded = f" {norm} "

    brand: list[str] = []
    keywords = list(keywords)
    for kw in keywords:  # the search keyword that is actually in the title
        parts = normalize(kw).split()
        if parts and all(any(w.startswith(p) for w in words) for p in parts):
            brand = parts
            break
    else:
        if keywords:
            brand = normalize(keywords[0]).split()

    models: list[str] = []
    for phrase in MODEL_PHRASES:
        if f" {phrase} " in padded:
            for part in _ALIASES.get(phrase, phrase).split():
                if part not in brand and part not in models:
                    models.append(part)

    refs: list[str] = []
    for w in words:  # reference / calibre numbers: 2609, 6309, 7s26, srpl87k1, pr516
        if (any(c.isdigit() for c in w) and len(w) >= 3 and not _YEAR.match(w)
                and not _NOT_A_REFERENCE.match(w) and w not in models and len(refs) < _MAX_REFS):
            refs.append(w)

    strong: list[str] = []
    if _LADY.search(norm):
        strong.append("lady")
    if _GOLD.search(norm) or _GOLD_WORD.search(norm):
        strong.append("gold")
    if _VINTAGE.search(norm):
        # Vintage and modern pieces of the same model are different markets
        # (a 1970s Seamaster Cosmic vs a new Seamaster Diver 300M).
        strong.append("vintage")
    movement: list[str] = []
    if _AUTOMATIC.search(norm):
        movement.append("automatic")
    elif _QUARTZ.search(norm):
        movement.append("quartz")
    return ModelSignature(tuple(brand), tuple(models), tuple(refs), tuple(strong), tuple(movement))


def comps_query(title: str, keywords: Iterable[str]) -> str:
    """eBay search words identifying the model in a listing title."""
    return model_signature(title, keywords).query


def ebay_sold_url(query: str, domain: str = "ebay.de", category_ids: str | None = "31387") -> str:
    """eBay search limited to sold, completed listings."""
    url = f"https://www.{domain}/sch/i.html?_nkw={quote_plus(query)}&LH_Sold=1&LH_Complete=1"
    if category_ids:
        url += f"&_sacat={category_ids.split(',')[0]}"
    return url
