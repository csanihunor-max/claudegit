"""Identify the specific watch in a listing, for finding comparable listings and
for the "eBay sold" link.

`identify` reads the title and (when available) the ad description:

- reference / model codes, the most precise identity: "ref: 2342.20.00",
  "SNK355K1", "6309-7040", "T065.430", from title or description;
- calibres: "Cal.: 7S26", "2609HA", "NH35";
- distinctive title words: every word that isn't generic ad vocabulary
  (karóra, férfi, szép, mechanikus, szovjet, colours, sizes, ...), so model names
  work even when they are in no list ("Anchar", "Dolce Vita", "Planet Ocean");
- attributes that change the price class: ladies', solid gold, vintage vs
  modern, movement (automatic / quartz / manual).

The description is only read here, never stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable
from urllib.parse import quote_plus

from .filters import normalize

# Multi-word model names kept together (normalized), with spelling fixes to what eBay sellers use.
MODEL_PHRASES = {
    "big zero": "big zero", "de ville": "de ville", "dolce vita": "dolce vita", "planet ocean": "planet ocean",
    "aqua terra": "aqua terra", "grande classique": "grande classique", "master collection": "master collection",
    "le locle": "le locle", "cocktail time": "cocktail time", "sea urchin": "sea urchin", "bell matic": "bell matic",
    "lord matic": "lord matic", "king seiko": "king seiko", "grand seiko": "grand seiko", "perpetual calendar":
    "perpetual calendar", "tv tokos": "tv", "ds action": "ds action", "ds podium": "ds podium", "pr 516": "pr 516",
    "pr 100": "pr 100", "sub 300": "sub 300", "t race": "t race", "blue ribbon": "blue ribbon", "seiko 5": "5",
    "sea star": "seastar",
}
_WORD_ALIASES = {
    "kopernikusz": "copernicus", "baltika": "baltica", "amfibia": "amphibia", "shturmanskie": "sturmanskie",
    "lordmatic": "lord matic", "oroknaptaras": "perpetual calendar", "orokkaptaras": "perpetual calendar",
    "dolcevita": "dolce vita", "chrono": "chronograph", "kronograf": "chronograph", "stopperes": "chronograph",
    "wostok": "vostok", "seamater": "seamaster", "hidroconquest": "hydroconquest",
}
# Generic ad vocabulary: Hungarian and English filler, condition, materials, colours,
# sizes. Built from the words that show up across 3+ brands in real titles.
STOPWORDS = frozenset("""
    a az egy es is s de la le el the and for with of in to new
    karora karoraja karorak ora oraja orak orat oram watch watches wristwatch ferfi ferfiaknak noi noknek mens men
    unisex boy fiu
    elado eladom eladnam elad adom csere cserelheto cserealap hirdetes akcio akcios ajandek olcson olcso
    uj ujszeru hordatlan vadiuj viseletlen szep szepen nagyon gyonyoru kivalo tokeletes jo mukodo mukodik
    mukodokepes megkimelt ritka egyedi kulonleges eredeti gyari orig original authentic genuine hibatlan
    allapot allapotban allapotu allapotu karcmentes szervizelt szerviz szervizrol utan bevizsgalt garancia
    garanciaval szamla szamlaval papir papirok papirjaival papirokkal dobozaban dobozzal dobozos box full set
    szett komplett keszlet
    svajci swiss japan japan japanese szovjet orosz ussr cccp sssr sovjet russian soviet retro regi vintage
    antik antique evek evekbol eves korai
    mechanikus mechanical automata automatic automatikus automat kvarc quartz elemes kezi huzos felhuzos
    felhuzhato kezihuzos kezzel felhuzo manual szerkezet szerkezettel szerkezetes szerkezetu movement
    koves ko jewels tipusu tipus modell model version valtozat kiadas edition limited limitalt collection
    kollekcio series serie klasszikus sport sports sportos diver buvar buvaros vizallo waterproof
    elegans elegant casual dress
    tok tokos tokkal acel acelos steel stainless rozsdamentes titanium titan fem aranyozott ezustozott
    krom kromozott bronz ceramic keramia szijjal szij szijas borszij lanccal lanc csattal csat karkoto
    black fekete blue kek white feher red piros green zold pink rozsaszin salmon silver ezust grey gray
    szurke brown barna dark sotet light vilagos bicolor mop diamond diamonds gyemant gyemantos
    szamlap szamlapos dial mutato mutatok uveg plexi zafir sapphire hardlex
    mm cm meret meretu nagy nagymeretu kicsi kis big small mini size oversize
    datum datumos datumkijelzos napos date day
    top best szuper super extra prestige premium luxus luxury
    hasznalt used beszamitas beszamitok nos arany beepites beepitett jelzett keszletbol webaruhazi
""".split())
# Other watch brands: mentioned for keyword stuffing ("Seiko 5 ... orient citizen"), never the watch itself.
OTHER_BRANDS = frozenset("""
    orient citizen casio tissot omega longines seiko raketa poljot vostok pobeda slava doxa certina rolex
    cartier swatch tudor breitling tag heuer hamilton zenith sekonda luch zim chaika chayka wostok invicta
    fossil diesel festina jacques lemans timex lorus pulsar guess michael kors iwc schaffhausen panerai
    patek philippe audemars piguet jaeger lecoultre oris junghans
""".split())

_LADY = re.compile(r"\b(noi|lady|ladies|holgy|damen)\b")
_GOLD = re.compile(r"\b(18k|14k|18 k|14 k|18kt|14kt|tomor arany|arany tok|arany tokos|solid gold|585|750|arany|aranyora)\b")
# In a description "arany" is often just a colour ("arany színű"): only karat marks count there.
_GOLD_STRICT = re.compile(r"\b(18k|14k|18 k|14 k|18kt|14kt|18 karat\w*|14 karat\w*|tomor arany|solid gold)\b")
_VINTAGE = re.compile(r"\b(szovjet|orosz|cccp|ussr|sssr|retro|regi|antik|vintage|(19[2-8]\d)(\w*)|[2-8]0 ?as evek\w*)\b")
_AUTOMATIC = re.compile(r"\b(automata|automatic|automatikus|automat|autómata)\b")
_QUARTZ = re.compile(r"\b(quartz|kvarc|elemes)\b")
_MANUAL = re.compile(r"\b(kezi huzos|felhuzos|kezihuzos|felhuzhato|manual wind|hand wind)\b")

# Reference / model codes, read from the raw (un-normalized) text.
_REF_LABELLED = re.compile(r"\bref(?:erencia|erence|\.|:)?\s*(?:sz(?:am|\.)?\s*)?[:#.]?\s*([A-Z0-9][A-Z0-9.\-/]{3,24}[A-Z0-9])",
                           re.IGNORECASE)
_SWISS_REF = re.compile(r"\b([TC]\d{3}\.\d{3}(?:\.\d{2}\.\d{3}\.\d{2})?)\b", re.IGNORECASE)
_CASE_REF = re.compile(r"\b([0-9A-Z]{4})\s?-\s?([0-9A-Z]{3,4})\b", re.IGNORECASE)   # 6309-7040, V701-6K00
_DOTTED_REF = re.compile(r"\b(\d{3,4}\.\d{2}(?:\.\d{2})?(?:\.\d{2}\.\d{2}\.\d{3})?)\b")          # 3551.20.00, 2541.80
_LONGINES_REF = re.compile(r"\b(L\d\.\d{3}\.\d\.\d{2}\.\d)\b", re.IGNORECASE)
_MODEL_CODE = re.compile(r"\b([A-Z]{2,5}\d{2,4}[A-Z0-9]{0,4})\b", re.IGNORECASE)
_CALIBER = re.compile(r"\b(?:cal(?:iber)?|kaliber)\s*\.?\s*[:#]?\s*(\d{4}[A-Z]{0,2}|\d[A-Z]\d{2}[A-Z]?|[A-Z]{2}\d{2}[A-Z]?)\b",
                      re.IGNORECASE)
_NOT_A_CODE = re.compile(r"^(MM|CM|KM|ATM|BAR|FT|HUF|EUR|DB|KT|NOS|GMT|UTC|USB|CEO)\d*$")
_YEAR = re.compile(r"^(19|20)\d\d$")
_MEASURE = re.compile(r"^\d+(mm|m|ft|eur|k|kt|db|cm|g|atm|bar|es|as|os)$")


@dataclass(frozen=True)
class Ident:
    brand: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()        # exact reference / model codes: strongest identity
    calibers: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()     # 3-4 digit numbers from the title (often a calibre or model)
    words: tuple[str, ...] = ()       # distinctive title words / model names
    lady: bool = False
    gold: bool = False
    vintage: bool = False
    movement: str | None = None       # automatic | quartz | manual
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def vague(self) -> bool:
        return not (self.refs or self.calibers or self.numbers or self.words)

    @property
    def query(self) -> str:
        """eBay search for this watch: the reference code when there is one, else its words."""
        brand = list(self.brand)
        if self.refs:
            parts = brand + [self.refs[0].lower()]
        else:
            parts = brand + list(self.words[:3]) + list(self.numbers[:1]) + list(self.calibers[:1])
            if self.vague and self.vintage:
                parts.append("vintage")
        if self.gold:
            parts.append("gold")
        if self.lady and "lady" not in parts:
            parts.append("lady")
        out: list[str] = []
        for p in parts:
            if p and p not in out:
                out.append(p)
        return " ".join(out)

    def to_json(self) -> str:
        d = asdict(self)
        d.pop("extra", None)
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | dict | None) -> "Ident | None":
        if not raw:
            return None
        d = json.loads(raw) if isinstance(raw, str) else dict(raw)
        try:
            return cls(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in _FIELDS})
        except TypeError:
            return None


_FIELDS = {"brand", "refs", "calibers", "numbers", "words", "lady", "gold", "vintage", "movement"}


def _codes(raw: str) -> tuple[list[str], list[str]]:
    refs: list[str] = []
    cals: list[str] = []

    def add(bucket: list[str], code: str) -> None:
        code = code.upper().strip(".-/")
        digits = sum(c.isdigit() for c in code)
        if not code or digits < 2 or digits >= 9 or _NOT_A_CODE.match(code) or code in bucket:
            return   # >= 9 digits smells like a phone number
        bucket.append(code)

    for m in _REF_LABELLED.finditer(raw):
        add(refs, m.group(1))
    for m in _SWISS_REF.finditer(raw):
        add(refs, m.group(1))
    for m in _LONGINES_REF.finditer(raw):
        add(refs, m.group(1))
    for m in _DOTTED_REF.finditer(raw):
        add(refs, m.group(1))
    for m in _CASE_REF.finditer(raw):
        a, b = m.group(1), m.group(2)
        if not _YEAR.match(a) and sum(c.isdigit() for c in a) >= 3 and sum(c.isdigit() for c in b) >= 2:
            add(refs, f"{a}-{b}")
    for m in _MODEL_CODE.finditer(raw):
        add(refs, m.group(1))
    for m in _CALIBER.finditer(raw):
        add(cals, m.group(1))
    # a calibre-looking code (7S26, NH35, 2609HA) listed as a "model code" is a calibre
    refs = [r for r in refs if r not in cals]
    return refs[:3], cals[:2]


def identify(title: str, details: str | None, keywords: Iterable[str]) -> Ident:
    norm = normalize(title)
    words_all = norm.split()
    keywords = list(keywords)

    brand: list[str] = []
    for kw in keywords:
        parts = normalize(kw).split()
        if parts and all(any(w.startswith(p) for w in words_all) for p in parts):
            brand = parts
            break
    else:
        if keywords:
            brand = normalize(keywords[0]).split()

    # model phrases first, so "de ville" / "dolce vita" stay one unit
    text = f" {norm} "
    words: list[str] = []
    for phrase, canonical in MODEL_PHRASES.items():
        if f" {phrase} " in text:
            if canonical not in words and canonical not in brand:
                words.append(canonical)
            text = text.replace(f" {phrase} ", " ")
    numbers: list[str] = []
    for w in text.split():
        w = _WORD_ALIASES.get(w, w)
        if w in brand or w in STOPWORDS or w in OTHER_BRANDS:
            continue
        if any(c.isdigit() for c in w):
            if w.isdigit() and 3 <= len(w) <= 4 and not _YEAR.match(w) and w not in numbers:
                numbers.append(w)
            continue   # codes are read from the raw text below; sizes/years dropped
        if len(w) < 2 or _MEASURE.match(w):
            continue
        if w not in words:
            words.append(w)

    detail_text = details or ""
    refs, cals = _codes(f"{title}\n{detail_text}")
    # a known model name mentioned only in the description ("Rakéta Kopernikusz" in the text)
    if details:
        dnorm = f" {normalize(detail_text)} "
        for phrase, canonical in MODEL_PHRASES.items():
            if len(phrase) > 4 and f" {phrase} " in dnorm and canonical not in words:
                words.append(canonical)
        for alias, canonical in _WORD_ALIASES.items():
            if len(alias) > 5 and f" {alias} " in dnorm and canonical not in words and canonical not in brand \
                    and canonical not in OTHER_BRANDS and canonical not in ("chronograph",):
                words.append(canonical)
    # numbers that are really part of a reference code aren't separate numbers
    numbers = [n for n in numbers if not any(n in r for r in refs + cals)]

    both = f"{norm} {normalize(detail_text)}"
    movement = ("automatic" if _AUTOMATIC.search(both) else "quartz" if _QUARTZ.search(both)
                else "manual" if _MANUAL.search(both) else None)
    return Ident(
        brand=tuple(brand), refs=tuple(refs), calibers=tuple(cals), numbers=tuple(numbers[:2]),
        words=tuple(words[:6]), lady=bool(_LADY.search(norm)),
        gold=bool(_GOLD.search(norm) or _GOLD_STRICT.search(normalize(detail_text))),
        vintage=bool(_VINTAGE.search(norm)), movement=movement,
    )


def comps_query(title: str, keywords: Iterable[str], details: str | None = None) -> str:
    """eBay search words identifying the watch in a listing."""
    return identify(title, details, keywords).query


def ebay_sold_url(query: str, domain: str = "ebay.de", category_ids: str | None = "31387") -> str:
    """eBay search limited to sold, completed listings."""
    url = f"https://www.{domain}/sch/i.html?_nkw={quote_plus(query)}&LH_Sold=1&LH_Complete=1"
    if category_ids:
        url += f"&_sacat={category_ids.split(',')[0]}"
    return url
