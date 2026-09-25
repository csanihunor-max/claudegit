"""Local dashboard: one page plus a small JSON API it calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from ..comps import comps_query, ebay_sold_url, model_signature
from ..market import GroupStats, is_hot, is_parts, resolve_reference, stats_from_storage
from ..config import AppConfig
from ..notify import SOURCE_LABELS
from ..storage import USER_STATUSES, Storage

SORTS = ("newest", "cheapest", "margin")
VIEWS = ("active", "interested", "bought", "ignore", "gone")


def create_app(config: AppConfig) -> Flask:
    app = Flask(__name__)
    app.config["WF"] = config

    def open_storage() -> Storage:
        return Storage(config.database)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            searches=[s.name for s in config.searches],
            sources=sorted({src for s in config.searches for src in s.sources}),
            source_labels=SOURCE_LABELS,
            hot_pct=round(config.hot_deal_ratio * 100),
        )

    @app.get("/api/listings")
    def listings():
        view = request.args.get("view", "active")
        if view not in VIEWS:
            abort(400, f"view must be one of {VIEWS}")
        sort = request.args.get("sort", "newest")
        if sort not in SORTS:
            abort(400, f"sort must be one of {SORTS}")
        search = request.args.get("search") or None
        source = request.args.get("source") or None
        max_price = _int_arg("max_price")

        storage = open_storage()
        try:
            # Bought/interested items often sell and vanish; keep showing them.
            rows = storage.dashboard_rows(include_gone=view in ("gone", "interested", "bought"))
            market = stats_from_storage(storage, config)
        finally:
            storage.close()

        items = []
        for row in rows:
            if view == "gone":
                if row["status"] != "gone":
                    continue
            elif view == "active":
                if row["user_status"] == "ignore":
                    continue
            elif row["user_status"] != view:
                continue
            if search and search not in row["searches"]:
                continue
            if source and row["source"] != source:
                continue
            if max_price is not None and (row["price_huf"] is None or row["price_huf"] > max_price):
                continue
            items.append(_decorate(row, config, search, market))

        if sort == "newest":
            items.sort(key=lambda i: i["first_seen"], reverse=True)
        elif sort == "cheapest":
            items.sort(key=lambda i: (i["price_huf"] is None, i["price_huf"] or 0))
        else:
            # best deal: cheapest relative to the reference; unreferenced last
            items.sort(key=lambda i: (i["reference_eur"] is None or not i["price_eur"],
                                      (i["price_eur"] or 0) / (i["reference_eur"] or 1)))
        return jsonify({"items": items, "count": len(items)})

    @app.get("/api/searches")
    def searches():
        storage = open_storage()
        try:
            rows = storage.dashboard_rows(include_gone=True)
        finally:
            storage.close()
        month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        out = []
        for s in config.searches:
            mine = [r for r in rows if s.name in r["searches"] and r["price_huf"]]
            ebay_prices = [r["price_huf"] / config.eur_huf_rate for r in mine
                           if r["source"] == "ebay" and r["status"] == "active"]
            # Ads that disappeared recently: sold or withdrawn, at their last asking price.
            gone_prices = [r["price_huf"] for r in mine if r["source"] == "jofogas" and r["status"] == "gone"
                           and (r["gone_at"] or "") >= month_ago]
            out.append({
                "name": s.name,
                "max_price_huf": s.max_price_huf,
                "reference_price_eur": s.reference_price_eur,
                "ebay_median_eur": round(median(ebay_prices)) if ebay_prices else None,
                "ebay_count": len(ebay_prices),
                "jofogas_gone_median_huf": round(median(gone_prices)) if gone_prices else None,
                "jofogas_gone_count": len(gone_prices),
                "comps_url": ebay_sold_url(comps_query(s.keywords[0], s.keywords), config.ebay.sold_domain,
                                           config.ebay.category_ids),
            })
        return jsonify(out)

    @app.post("/api/listings/<source>/<listing_id>/status")
    def set_status(source: str, listing_id: str):
        # JSON-only: a plain cross-site form post can't send application/json.
        if not request.is_json:
            abort(415)
        status = (request.get_json(silent=True) or {}).get("status")
        if status is not None and status not in USER_STATUSES:
            abort(400, f"status must be one of {USER_STATUSES} or null")
        storage = open_storage()
        try:
            if not storage.set_user_status(source, listing_id, status):
                abort(404)
        finally:
            storage.close()
        return jsonify({"ok": True, "status": status})

    return app


def _int_arg(name: str) -> int | None:
    raw = (request.args.get(name) or "").replace(" ", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        abort(400, f"{name} must be a whole number")


def _decorate(
    row: dict[str, Any], config: AppConfig, selected_search: str | None, market: dict[str, GroupStats]
) -> dict[str, Any]:
    rate = config.eur_huf_rate
    keywords = [k for s in config.searches if s.name in row["searches"] for k in s.keywords]
    sig = model_signature(row["title"], keywords)
    model_key = sig.query
    comps_url = ebay_sold_url(model_key, config.ebay.sold_domain, config.ebay.category_ids)
    search_refs = [s.reference_price_eur for s in config.searches
                   if s.name in row["searches"] and s.reference_price_eur
                   and (selected_search is None or s.name == selected_search)]
    ref = resolve_reference(sig.group_keys, config.model_references, market, rate,
                            max(search_refs) if search_refs else None, market_ok=sig.market_ok)
    reference = ref.eur if ref else None
    reference_from = ref.source if ref else None
    price_huf = row["price_huf"]
    price_eur = price_huf / rate if price_huf is not None else None
    margin = reference - price_eur if reference is not None and price_eur is not None else None
    return {
        "source": row["source"],
        "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
        "listing_id": row["listing_id"],
        "title": row["title"],
        "url": row["url"],
        "thumbnail_url": row["thumbnail_url"],
        "location": row["location"],
        "price": row["price"],
        "currency": row["currency"],
        "price_huf": price_huf,
        "price_eur": round(price_eur, 1) if price_eur is not None else None,
        "reference_eur": reference,
        "margin_eur": round(margin, 1) if margin is not None else None,
        "margin_pct": round(100 * margin / reference) if margin is not None and reference else None,
        "hot": is_hot(price_huf, ref, rate, config.hot_deal_ratio, row["title"]),
        "parts": is_parts(row["title"]),
        "reference_key": ref.key if ref else None,
        "reference_stats": ref.stats.as_dict() if ref and ref.stats else None,
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "status": row["status"],
        "gone_at": row["gone_at"],
        "user_status": row["user_status"],
        "searches": row["searches"],
        "price_history": row["price_history"],
        "comps_url": comps_url,
        "model_key": model_key,
        "reference_from": reference_from,
    }
