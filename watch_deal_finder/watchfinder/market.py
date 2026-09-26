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
MAX_COMPS = 8            # comparables used per listing
MIN_COMPS = 4            # to show a market reference at all
MIN_COMPS_HOT = 5        # to flag 🔥 from one
MAX_SPREAD = 0.7         # (p75 - p25) / median of the comparables, for 🔥
MIN_SIMILARITY = 1.0

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


@dataclass
class _Entry:
    id: str
    price: int
    ident: Ident
    tokens: frozenset[str] = field(default_factory=frozenset)
    seen: str = ""


def _tokens(ident: Ident) -> frozenset[str]:
    return frozenset(list(ident.words) + [f"#{n}" for n in ident.numbers])


def _compatible(a: Ident, b: Ident) -> bool:
    if a.brand != b.brand or a.lady != b.lady or a.gold != b.gold or a.vintage != b.vintage:
        return False
    return not (a.movement and b.movement and a.movement != b.movement)


class MarketIndex:
    """All comparable-eligible listings, indexed for finding the most similar ones."""

    def __init__(self, records: Iterable[Mapping[str, Any]], now: datetime | None = None):
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
            self.entries[r["id"]] = _Entry(r["id"], int(price), ident, _tokens(ident), r.get("first_seen") or "")
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

    def comparables(self, ident: Ident, exclude_id: str | None = None) -> tuple[list[str], str | None, bool]:
        """(comparable ids, what they share, generic?) for a listing's identity."""
        b = ident.brand
        if ident.vague:
            ids = [i for i in self._vague.get(b, ()) if i != exclude_id and _compatible(ident, self.entries[i].ident)]
            ids.sort(key=lambda i: (self.entries[i].seen, i), reverse=True)   # deterministic: newest, then id
            unique, seen_ads = [], set()
            for i in ids:
                dup = (self.entries[i].ident, self.entries[i].price)
                if dup not in seen_ads:
                    seen_ads.add(dup)
                    unique.append(i)
            ids = unique
            return ids[:MAX_COMPS * 3], None, True   # vague: a wider sample of equally vague ads

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
            dup = (other.ident, other.price)
            if dup in seen_ads:
                continue
            seen_ads.add(dup)
            if not _compatible(ident, other.ident):
                continue
            score, shared = 0.0, ""
            same_ref = set(ident.refs) & set(other.ident.refs)
            if same_ref:
                score += 3.0
                shared = f"ref {sorted(same_ref)[0]}"
            if set(ident.calibers) & set(other.ident.calibers):
                score += 1.0
            common = tokens & other.tokens
            if common:
                union_w = self._weight(tokens | other.tokens)
                score += 2.0 * self._weight(common) / union_w if union_w else 0.0
                if not shared:
                    rare_first = sorted(common, key=lambda t: -self._idf.get(t, 0))[:3]
                    shared = " ".join(list(b) + [t.lstrip("#") for t in rare_first])
            if score >= MIN_SIMILARITY:
                scored.append((score, other.seen, cid, shared))
        # Deterministic order (otherwise the chosen comparables, and so every listing
        # document, could change between runs): most similar, then newest, then id.
        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        scored.sort(key=lambda x: -x[0])
        top = scored[:MAX_COMPS]
        basis = top[0][3] if top else None
        return [cid for _, _, cid, _ in top], basis, False

    def reference(self, ident: Ident, eur_huf_rate: float, exclude_id: str | None = None) -> Reference | None:
        ids, basis, generic = self.comparables(ident, exclude_id)
        if len(ids) < MIN_COMPS:
            return None
        stats = stats_of(self.entries[i].price for i in ids)
        return Reference(stats.median / eur_huf_rate, "market", basis, stats, tuple(ids[:MAX_COMPS]), generic)


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
