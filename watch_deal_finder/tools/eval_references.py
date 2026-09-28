"""Backtest the comparables engine on real listings (leave-one-out).

For every active Jófogás listing: hide it (and any relisted copy), compute its
reference from the remaining ads, and compare with the listing's own asking
price. A good reference sits close to what such a watch is typically offered
for, so the typical error should be small; real deals show up as large misses.

    python -m tools.eval_references DUMP_DIR               # current settings
    python -m tools.eval_references DUMP_DIR --grid        # compare settings

DUMP_DIR is a database dump as the cloud run makes it (shards/*.json).
Reported per setting:
  coverage   share of listings that get a reference at all
  median err typical |price - reference| / reference (log-symmetric)
  within 25% share of references within 25% of the listing's price
  fire       listings that would be flagged 🔥 (price <= 50% of reference, 5+ tight comps)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watchfinder.cloudsync import load_docs  # noqa: E402
from watchfinder.comps import Ident  # noqa: E402
from watchfinder.market import DEFAULT_PARAMS, MarketIndex, Params, is_hot, is_parts  # noqa: E402

RATE = 395.0


def load_records(dump: Path) -> list[dict]:
    records = []
    for body in load_docs(dump / "shards").values():
        for did, d in (body.get("items") or {}).items():
            if not isinstance(d, dict) or "title" not in d:
                continue
            ident = Ident.from_json(d.get("ident"))
            if ident is None:
                continue
            records.append({"id": did, "source": d["source"], "title": d["title"], "price_huf": d.get("price_huf"),
                            "status": d.get("status"), "gone_at": d.get("gone_at"),
                            "first_seen": d.get("first_seen"), "ident": ident})
    return records


def evaluate(records: list[dict], params: Params) -> dict:
    index = MarketIndex(records, params=params)
    targets = [r for r in records if r["status"] == "active" and r["id"] in index.entries]
    errors, errors_specific, errors_generic, fire = [], [], [], 0
    for r in targets:
        ref = index.reference(r["ident"], RATE, exclude_id=r["id"])
        if not ref:
            continue
        err = abs(math.log(r["price_huf"] / ref.stats.median))
        errors.append(err)
        (errors_generic if ref.generic else errors_specific).append(err)
        fire += is_hot(r["price_huf"], ref, RATE, 0.5, r["title"])

    def pct(xs):
        return round(100 * (math.exp(median(xs)) - 1), 1) if xs else None

    return {
        "listings": len(targets),
        "coverage": round(100 * len(errors) / max(len(targets), 1), 1),
        "median_err_pct": pct(errors),
        "specific_err_pct": pct(errors_specific),
        "generic_err_pct": pct(errors_generic),
        "within_25_pct": round(100 * sum(e <= math.log(1.25) for e in errors) / max(len(errors), 1), 1),
        "fire": fire,
    }


GRID = {
    "current": DEFAULT_PARAMS,
    "k=5": replace(DEFAULT_PARAMS, max_comps=5),
    "k=8": replace(DEFAULT_PARAMS, max_comps=8),
    "min_comps=3": replace(DEFAULT_PARAMS, min_comps=3),
    "min_comps=5": replace(DEFAULT_PARAMS, min_comps=5),
    "similarity>=1.0": replace(DEFAULT_PARAMS, min_similarity=1.0),
    "similarity>=0.7": replace(DEFAULT_PARAMS, min_similarity=0.7),
    "weighted median": replace(DEFAULT_PARAMS, estimator="weighted"),
    "no trim": replace(DEFAULT_PARAMS, trim=None),
    "trim x1.5": replace(DEFAULT_PARAMS, trim=1.5),
    "trim x2": replace(DEFAULT_PARAMS, trim=2.0),
    "ref-only>=3": replace(DEFAULT_PARAMS, ref_only=3),
    "vague 8": replace(DEFAULT_PARAMS, vague_max=8),
    "vague 40": replace(DEFAULT_PARAMS, vague_max=40),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--grid", action="store_true")
    args = ap.parse_args(argv)
    records = load_records(args.dump)
    print(f"{len(records)} listings loaded ({sum(is_parts(r['title']) for r in records)} parts)")
    grid = GRID if args.grid else {"current": DEFAULT_PARAMS}
    for name, params in grid.items():
        print(f"{name:18} {json.dumps(evaluate(records, params))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
