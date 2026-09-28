"""Reference prices from comparable listings ("comps"), like valuing a house.

For each listing we look for the Jófogás ads most similar to it (active, or gone
in the last `WINDOW_DAYS` days) and take the median of their prices:

- candidates must be the same brand and the same price class: ladies' vs men's,
  solid gold vs not, vintage vs modern, and the same movement when both are known;
- similarity: an identical reference / model code (2342.20.00, SNK355K1) counts
  most, then a shared calibre, then the distinctive title words they share,
  weighted by how rare each word is (IDF), so "copernicus" counts more than a
  word many ads use;
- the best `MAX_COMPS` matches above a threshold are the comparables; a listing
  whose title says nothing specific is compared only with other equally vague
  ads of the same kind, and that is labelled as such.

Left out as comparables: parts / defective items, lots, accessories and
placeholder prices under 1 000 Ft.

Reference order for a listing (first that exists wins): the owner's own
reference for this watch (checked against eBay sold prices), the median of its
comparables, the search's reference_price_eur.

These are asking prices on the local market, not sale prices, and are labelled
that way wherever they are shown.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Mapping

from .comps import Ident, identify
from .filters import normalize

WINDOW_DAYS = 60
MIN_PRICE_HUF = 1_000
# Tuned by backtesting on ~800 real listings (python -m tools.eval_references DUMP --grid):
# for each ad, how close its reference comes to its own asking price.
MAX_COMPS = 6            # comparables used per listing (8 and 12 were less accurate)
MIN_COMPS = 4            # to show a market reference at all
MIN_COMPS_HOT = 5        # to flag 🔥 from one
MAX_SPREAD = 0.7         # (p75 - p25) / median of the comparables, for 🔥
MIN_SIMILARITY = 0.85    # 1.0 lost coverage for no accuracy; 0.7 let in wrong models
TRIM = 1.7               # drop comparables priced beyond 1.7x / below 1/1.7 of their median
VAGUE_MAX = 24           # vague vintage titles: sample of up to this many equally vague ads

# Parts, broken or incomplete watches, lots, accessories and conversions: not
# comparable with a complete watch (normalized titles).
_PARTS_ANYWHERE = re.compile(
    r"alkatresz|felhuzoszar|tengely|szamlap|hibas|javitasra|javitando|nem mukodik|nem jar|hianyos|hianyzik|"
    r"szerkezet nelkul|csak szerkezet|tok nelkul|zsebora|beepites|gumiszij|not working|for parts|spares|defekt"
)
_PARTS_WORD = re.compile(r"\b(doboz|dobozok|szij|csat|mutato|mutatok|parts|repair|\d+ db)\b")


def is_parts(title: str) -> bool:
    norm = normalize(title)
    return bool(_PARTS_ANYWHERE.search(norm) or _PARTS_WORD.search(norm))


@dataclass(frozen=True)
class GroupStats:
    median: int
    p25: int
    p75: int
    n: int

    @property
    def spread(self) -> float:
        return (self.p75 - self.p25) / self.median if self.median else 99.0

    def as_dict(self) -> dict[str, int]:
        return {"median": self.median, "p25": self.p25, "p75": self.p75, "n": self.n}


@dataclass(frozen=True)
class Reference:
    eur: float
    source: str                        # "you" | "market" | "search"
    key: str | None = None             # your ref: the watch's query; market: what the comps share
    stats: GroupStats | None = None
    comp_ids: tuple[str, ...] = ()     # the comparable listings, most similar first
    generic: bool = False              # compared with other vague ads only

    def to_doc(self) -> dict[str, Any]:
        d: dict[str, Any] = {"source": self.source, "eur": round(self.eur, 2), "basis": self.key,
                             "generic": self.generic}
        if self.stats:
            d.update(self.stats.as_dict())
        if self.comp_ids:
            d["comps"] = list(self.comp_ids)
        return d


def _quantile(sorted_values: list[int], q: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def stats_of(prices: Iterable[int]) -> GroupStats:
    values = sorted(int(p) for p in prices)
    return GroupStats(int(round(median(values))), int(round(_quantile(values, 0.25))),
                      int(round(_quantile(values, 0.75))), len(values))


@dataclass(frozen=True)
class Params:
    """Tuning knobs of the comparables engine (see tools/eval_references.py)."""
    max_comps: int = MAX_COMPS
    min_comps: int = MIN_COMPS
    min_similarity: float = MIN_SIMILARITY
    ref_weight: float = 3.0       # an identical reference / model code
    cal_weight: float = 1.0       # a shared calibre
    word_weight: float = 2.0      # x IDF-weighted overlap of distinctive words (0..1)
    vague_max: int = VAGUE_MAX
    estimator: str = "median"     # "median" | "weighted" (similarity-weighted median: tested, worse)
    trim: float | None = TRIM     # drop comparables priced beyond x / trim of their median
    ref_only: int = 0             # with >= this many same-reference comparables, use only those (0 = off)


DEFAULT_PARAMS = Params()


def weighted_median(values: list[int], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return float(v)
    return float(pairs[-1][0])


@dataclass
class _Entry:
    id: str
    price: int
    ident: Ident
    tokens: frozenset[str] = field(default_factory=frozenset)
    seen: str = ""
    dup_key: tuple = ()          # (normalized title, price): the same ad relisted


def _tokens(ident: Ident) -> frozenset[str]:
    return frozenset(list(ident.words) + [f"#{n}" for n in ident.numbers])


def _compatible(a: Ident, b: Ident) -> bool:
    if a.brand != b.brand or a.lady != b.lady or a.gold != b.gold or a.vintage != b.vintage:
        return False
    return not (a.movement and b.movement and a.movement != b.movement)


class MarketIndex:
    """All comparable-eligible listings, indexed for finding the most similar ones."""

    def __init__(self, records: Iterable[Mapping[str, Any]], now: datetime | None = None,
                 params: Params = DEFAULT_PARAMS):
        self.params = params
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=WINDOW_DAYS)).isoformat()
        self.entries: dict[str, _Entry] = {}
        for r in records:
            price = r.get("price_huf")
            if r.get("source") != "jofogas" or not price or price < MIN_PRICE_HUF:
                continue
            if r.get("status") == "gone" and (r.get("gone_at") or "") < cutoff:
                continue
            if is_parts(r.get("title") or ""):
                continue
            ident = r["ident"]
            self.entries[r["id"]] = _Entry(r["id"], int(price), ident, _tokens(ident), r.get("first_seen") or "",
                                           (normalize(r.get("title") or ""), int(price)))
        # inverted indexes, per brand
        self._by_token: dict[tuple, set[str]] = {}
        self._by_ref: dict[tuple, set[str]] = {}
        self._by_cal: dict[tuple, set[str]] = {}
        self._vague: dict[tuple, set[str]] = {}
        df: dict[str, int] = {}
        for e in self.entries.values():
            b = e.ident.brand
            for t in e.tokens:
                self._by_token.setdefault((b, t), set()).add(e.id)
                df[t] = df.get(t, 0) + 1
            for ref in e.ident.refs:
                self._by_ref.setdefault((b, ref), set()).add(e.id)
            for cal in e.ident.calibers:
                self._by_cal.setdefault((b, cal), set()).add(e.id)
            if e.ident.vague:
                self._vague.setdefault(b, set()).add(e.id)
        n = max(len(self.entries), 1)
        self._idf = {t: math.log(1 + n / c) for t, c in df.items()}

    def _weight(self, tokens: Iterable[str]) -> float:
        return sum(self._idf.get(t, math.log(1 + len(self.entries) + 1)) for t in tokens)

    def comparables(
        self, ident: Ident, exclude_id: str | None = None
    ) -> tuple[list[tuple[str, float]], str | None, bool]:
        """([(comparable id, similarity)], what they share, generic?) for a listing's identity."""
        P = self.params
        b = ident.brand
        # the listing itself, and any relisted copy of the same ad, are never its own comparables
        own = self.entries.get(exclude_id or "")
        own_key = own.dup_key if own else None
        if ident.vague:
            # A vague title only says "a Pobeda": fine for vintage Soviet pieces, which are
            # alike, but a vague modern "Doxa óra" could be anything (backtest: ~100% off).
            if not ident.vintage:
                return [], None, True
            ids = [i for i in self._vague.get(b, ()) if i != exclude_id and self.entries[i].dup_key != own_key
                   and _compatible(ident, self.entries[i].ident)]
            ids.sort(key=lambda i: (self.entries[i].seen, i), reverse=True)   # deterministic: newest, then id
            unique, seen_ads = [], set()
            for i in ids:
                dup = self.entries[i].dup_key
                if dup not in seen_ads:
                    seen_ads.add(dup)
                    unique.append(i)
            ids = unique
            return [(i, 1.0) for i in ids[:P.vague_max]], None, True   # vague: a wider sample of vague ads

        tokens = _tokens(ident)
        candidates: set[str] = set()
        for t in tokens:
            candidates |= self._by_token.get((b, t), set())
        for ref in ident.refs:
            candidates |= self._by_ref.get((b, ref), set())
        for cal in ident.calibers:
            candidates |= self._by_cal.get((b, cal), set())
        candidates.discard(exclude_id or "")

        scored: list[tuple[float, str, str]] = []
        seen_ads: set[tuple] = set()
        for cid in sorted(candidates):
            other = self.entries[cid]
            # the same ad posted twice (dealers relist) counts once
            dup = other.dup_key
            if dup in seen_ads or dup == own_key:
                continue
            if not _compatible(ident, other.ident):
                continue
            seen_ads.add(dup)
            score, shared = 0.0, ""
            same_ref = set(ident.refs) & set(other.ident.refs)
            if same_ref:
                score += P.ref_weight
                shared = f"ref {sorted(same_ref)[0]}"
            if set(ident.calibers) & set(other.ident.calibers):
                score += P.cal_weight
            common = tokens & other.tokens
            if common:
                union_w = self._weight(tokens | other.tokens)
                score += P.word_weight * self._weight(common) / union_w if union_w else 0.0
                if not shared:
                    rare_first = sorted(common, key=lambda t: -self._idf.get(t, 0))[:3]
                    shared = " ".join(list(b) + [t.lstrip("#") for t in rare_first])
            if score >= P.min_similarity:
                scored.append((score, other.seen, cid, shared, bool(same_ref)))
        # Deterministic order (otherwise the chosen comparables, and so every listing
        # document, could change between runs): most similar, then newest, then id.
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        scored.sort(key=lambda x: -x[0])
        if P.ref_only:
            same = [x for x in scored if x[4]]
            if len(same) >= P.ref_only:
                scored = same
        top = scored[:P.max_comps]
        basis = top[0][3] if top else None
        return [(cid, score) for score, _, cid, _, _ in top], basis, False

    def reference(self, ident: Ident, eur_huf_rate: float, exclude_id: str | None = None) -> Reference | None:
        P = self.params
        comps, basis, generic = self.comparables(ident, exclude_id)
        if P.trim and len(comps) >= P.min_comps:
            mid = median(self.entries[i].price for i, _ in comps)
            comps = [(i, w) for i, w in comps if mid / P.trim <= self.entries[i].price <= mid * P.trim]
        if len(comps) < P.min_comps:
            return None
        prices = [self.entries[i].price for i, _ in comps]
        stats = stats_of(prices)
        if P.estimator == "weighted":
            stats = GroupStats(int(round(weighted_median(prices, [w for _, w in comps]))), stats.p25, stats.p75,
                               stats.n)
        ids = tuple(i for i, _ in comps)
        return Reference(stats.median / eur_huf_rate, "market", basis, stats, ids[:P.max_comps], generic)


def resolve_reference(
    ident: Ident,
    own_refs: Mapping[str, float],
    index: MarketIndex | None,
    eur_huf_rate: float,
    search_ref_eur: float | None = None,
    exclude_id: str | None = None,
) -> Reference | None:
    if ident.query in own_refs:
        return Reference(own_refs[ident.query], "you", ident.query)
    if index is not None:
        ref = index.reference(ident, eur_huf_rate, exclude_id)
        if ref:
            return ref
    if search_ref_eur:
        return Reference(search_ref_eur, "search")
    return None


def is_hot(price_huf: int | None, ref: Reference | None, eur_huf_rate: float, ratio: float, title: str = "") -> bool:
    if price_huf is None or ref is None or price_huf < MIN_PRICE_HUF or is_parts(title):
        return False
    if ref.source == "market" and (ref.stats is None or ref.stats.spread > MAX_SPREAD
                                   or ref.stats.n < MIN_COMPS_HOT):
        return False
    return price_huf <= ref.eur * eur_huf_rate * ratio


def listing_records(storage, config) -> list[dict[str, Any]]:
    """Every stored listing with its identity, for `MarketIndex`."""
    from .cloudsync import doc_id

    keywords = {s.name: s.keywords for s in config.searches}
    searches: dict[tuple[str, str], list[str]] = {}
    for r in storage.conn.execute("SELECT source, listing_id, search_name FROM listing_searches ORDER BY search_name"):
        searches.setdefault((r[0], r[1]), []).append(r[2])
    records = []
    for r in storage.conn.execute(
        "SELECT source, listing_id, title, price_huf, status, gone_at, first_seen, ident FROM listings"
    ):
        ident = Ident.from_json(r[7])
        if ident is None:
            kws = [k for name in searches.get((r[0], r[1]), []) for k in keywords.get(name, ())]
            ident = identify(r[2], None, kws)
        records.append({"id": doc_id(r[0], r[1]), "source": r[0], "listing_id": r[1], "title": r[2],
                        "price_huf": r[3], "status": r[4], "gone_at": r[5], "first_seen": r[6], "ident": ident})
    return records


def index_from_storage(storage, config) -> MarketIndex:
    return MarketIndex(listing_records(storage, config))
