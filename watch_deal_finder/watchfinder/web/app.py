"""Local dashboard: one page plus a small JSON API it calls."""

from __future__ import annotations

from statistics import median
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

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
            items.append(_decorate(row, config, search))

        if sort == "newest":
            items.sort(key=lambda i: i["first_seen"], reverse=True)
        elif sort == "cheapest":
            items.sort(key=lambda i: (i["price_huf"] is None, i["price_huf"] or 0))
        else:
            items.sort(key=lambda i: (i["margin_eur"] is None, -(i["margin_eur"] or 0)))
        return jsonify({"items": items, "count": len(items)})

    @app.get("/api/searches")
    def searches():
        storage = open_storage()
        try:
            rows = storage.dashboard_rows()
        finally:
            storage.close()
        out = []
        for s in config.searches:
            ebay_prices = [r["price_huf"] / config.eur_huf_rate for r in rows
                           if r["source"] == "ebay" and s.name in r["searches"] and r["price_huf"]]
            out.append({
                "name": s.name,
                "max_price_huf": s.max_price_huf,
                "reference_price_eur": s.reference_price_eur,
                "ebay_median_eur": round(median(ebay_prices)) if ebay_prices else None,
                "ebay_count": len(ebay_prices),
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


def _decorate(row: dict[str, Any], config: AppConfig, selected_search: str | None) -> dict[str, Any]:
    rate = config.eur_huf_rate
    refs = [s.reference_price_eur for s in config.searches
            if s.name in row["searches"] and s.reference_price_eur
            and (selected_search is None or s.name == selected_search)]
    reference = max(refs) if refs else None
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
        "hot": bool(reference and price_huf is not None and price_huf <= reference * rate * config.hot_deal_ratio),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "status": row["status"],
        "gone_at": row["gone_at"],
        "user_status": row["user_status"],
        "searches": row["searches"],
        "price_history": row["price_history"],
    }
