"""Automatic per-model market references from the listings we have seen.

Every Jófogás listing contributes its price to each of its model group keys
(see `comps.model_signature`). A group's reference is the median price of its
listings, with the middle-50% range (p25-p75) as a spread measure, built from
active listings plus those that disappeared in the last `WINDOW_DAYS` days.
Left out: parts / defective items and placeholder prices under 1 000 Ft.

Reference order for a listing (first that exists wins):
1. a per-model reference the owner set (checked against eBay sold prices),
   matched on any of the listing's group keys, most specific first;
2. the Jófogás market median of the most specific group with >= MIN_SAMPLES;
3. the search's reference_price_eur, if one is configured.

These are asking prices on the local market, not sale prices, and are
labelled that way wherever they are shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Mapping

from .filters import normalize

MIN_SAMPLES = 5          # to show a market reference at all
MIN_SAMPLES_HOT = 8      # to flag 🔥 from one
WINDOW_DAYS = 60
MIN_PRICE_HUF = 1_000
# 🔥 from a market median only when the group isn't all over the place:
# (p75 - p25) / median must not exceed this.
MAX_SPREAD = 0.7

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
    source: str                 # "you" | "market" | "search"
    key: str | None = None      # the group key it came from
    stats: GroupStats | None = None

    def label(self) -> str:
        if self.source == "you":
            return f"your ref for '{self.key}'"
        if self.source == "market" and self.stats:
            return f"Jófogás median of {self.stats.n} '{self.key}' ads"
        return "search ref"


def _quantile(sorted_values: list[int], q: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def market_stats(listings: Iterable[Mapping[str, Any]], now: datetime | None = None) -> dict[str, GroupStats]:
    """Group statistics from listing records with: source, title, price_huf, status,
    gone_at, group_keys."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    prices: dict[str, list[int]] = {}
    for item in listings:
        price = item.get("price_huf")
        if item.get("source") != "jofogas" or not price or price < MIN_PRICE_HUF:
            continue
        if item.get("status") == "gone" and (item.get("gone_at") or "") < cutoff:
            continue
        if is_parts(item.get("title") or "") or item.get("market_ok") is False:
            continue
        for key in item.get("group_keys") or []:
            prices.setdefault(key, []).append(int(price))
    stats = {}
    for key, values in prices.items():
        values.sort()
        stats[key] = GroupStats(
            median=int(round(median(values))), p25=int(round(_quantile(values, 0.25))),
            p75=int(round(_quantile(values, 0.75))), n=len(values),
        )
    return stats


def resolve_reference(
    group_keys: list[str],
    own_refs: Mapping[str, float],
    stats: Mapping[str, GroupStats],
    eur_huf_rate: float,
    search_ref_eur: float | None = None,
    market_ok: bool = True,
) -> Reference | None:
    for key in group_keys:
        if key in own_refs:
            return Reference(own_refs[key], "you", key)
    for key in group_keys if market_ok else ():
        s = stats.get(key)
        if s and s.n >= MIN_SAMPLES:
            return Reference(s.median / eur_huf_rate, "market", key, s)
    if search_ref_eur:
        return Reference(search_ref_eur, "search")
    return None


def is_hot(price_huf: int | None, ref: Reference | None, eur_huf_rate: float, ratio: float, title: str = "") -> bool:
    if price_huf is None or ref is None or price_huf < MIN_PRICE_HUF or is_parts(title):
        return False
    if ref.source == "market" and (ref.stats is None or ref.stats.spread > MAX_SPREAD
                                   or ref.stats.n < MIN_SAMPLES_HOT):
        return False
    return price_huf <= ref.eur * eur_huf_rate * ratio


def stats_from_dicts(raw: Mapping[str, Mapping[str, int]]) -> dict[str, GroupStats]:
    return {k: GroupStats(int(v["median"]), int(v["p25"]), int(v["p75"]), int(v["n"])) for k, v in raw.items()}


def listing_records(storage, config) -> list[dict[str, Any]]:
    """Every stored listing with its model groups, for `market_stats`."""
    from .comps import model_signature

    keywords = {s.name: s.keywords for s in config.searches}
    searches: dict[tuple[str, str], list[str]] = {}
    for r in storage.conn.execute("SELECT source, listing_id, search_name FROM listing_searches"):
        searches.setdefault((r[0], r[1]), []).append(r[2])
    records = []
    for r in storage.conn.execute("SELECT source, listing_id, title, price_huf, status, gone_at FROM listings"):
        kws = [k for name in searches.get((r[0], r[1]), []) for k in keywords.get(name, ())]
        sig = model_signature(r[2], kws)
        records.append({"source": r[0], "listing_id": r[1], "title": r[2], "price_huf": r[3], "status": r[4],
                        "gone_at": r[5], "group_keys": sig.group_keys, "market_ok": sig.market_ok,
                        "signature": sig})
    return records


def stats_from_storage(storage, config) -> dict[str, GroupStats]:
    return market_stats(listing_records(storage, config))
