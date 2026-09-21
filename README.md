# Hardverapro Arbitrage Scraper

Polls one or more hardverapro.hu search-result pages every hour, tracks
prices per item over time, and flags listings priced well below that
item's own recent second-hand market price.

## Quickstart

1. `pip install -r requirements.txt`
2. `cp .env.example .env` — works as-is, pre-filled with every
   hardverapro.hu electronics/computing category, 53 in total
   (`hardverapro_arbitrage/categories.py`'s `DEFAULT_SEARCH_URLS` — the
   two aren't linked automatically, so if you add/remove a category
   there, copy the change into `.env.example` too). Edit `HA_SEARCH_URLS`
   in `.env` to track a specific saved search or a narrower set instead.
3. `python -m hardverapro_arbitrage --all`
4. Open `http://<that machine>:8765/` — deals appear as the hourly loop finds them

## Selectors are verified against the real site

`hardverapro_arbitrage/scraper/parser.py` (`_SELECTORS`) was checked
against live hardverapro.hu category/search pages (2026-09-21) — ad cards
are `<li class="media" data-uadid="...">`, and the parser was run
end-to-end against real listings (100 motherboard ads, 97 phone ads) with
no crashes and correct titles/prices/locations/ids.

If hardverapro.hu changes its markup later and listings stop showing up,
re-check it the same way:

```bash
# straight from a live search-results URL...
python -m hardverapro_arbitrage.tools.inspect_html "https://hardverapro.hu/aprok/<category>/index.html"

# ...or a page you saved locally (browser -> Save Page As)
python -m hardverapro_arbitrage.tools.inspect_html path/to/saved_page.html
```

It prints exactly what the parser extracted. Compare that to the page in
your browser — 0 listings with a "0 listing cards matched" warning means
the `listing_card` selector no longer matches; listings printed but with
wrong titles/prices means one of the more specific selectors needs
updating. Same dict, same fix either way.

hardverapro.hu's `robots.txt` disallows crawling paginated *search*
results (`keres.php?...offset=`) and asks for a 1-second crawl delay.
This scraper never touches `keres.php`, so it's compliant by default —
`HA_REQUEST_DELAY` defaults to 2 seconds, don't lower it below 1. It does
follow *category browse* pagination (`index.html?offset=100`,
`?offset=200`, ...) up to `HA_MAX_PAGES_PER_CATEGORY` (default 6, i.e. up
to ~600 listings per category) — a category page's ~100-per-page cap
otherwise means most categories are only ever seen partially. This is a
different endpoint than the one robots.txt disallows, verified against a
real fetch before relying on it.

A listing the seller has marked **"jegelve"** ("on ice" — reserved for
another buyer, pending a sale) is excluded entirely, not just flagged: it
isn't actually available, and its price shouldn't count as a market
comparable either — a reserved item's price reflects an already-agreed
deal, not what it's currently obtainable for. Detected from the site's own
`uad-status-iced` marker on the listing card.

## How a "deal" is decided

The bot computes its own reference price per item — the **median of all
other recent listings for the same normalized item title**, from its own
price-history database. A listing is flagged as a deal once it's priced
`HA_DEAL_THRESHOLD` (default 5%) or more below that median, and only once
at least `HA_MIN_SAMPLES` (default 2) other listings of that item have
been seen — otherwise there's nothing to compare against. Checked against
real collected data: most duplicate groups only ever reach 2 other
listings, so an earlier default of 3 silently discarded most of them
rather than reflecting real caution — 2 is the floor that still means
something (a median of 1 other listing isn't really a "market").

Titles are normalized (`scraper/normalize.py`) by lowercasing, stripping
accents/punctuation, and removing common Hungarian marketplace filler
words ("eladó", "garanciával", "használt", ...) so e.g. "Eladó iPhone 12
128GB garanciával" and "iPhone 12 128 GB" are recognized as the same item.
This is intentionally conservative — it only merges listings whose titles
reduce to an *identical* key, so it never guesses that two differently
named products are the same thing. The tradeoff: categories with heavy
model/variant diversity (camera gear is the clearest example — every
listing names a different lens/body combo) rarely produce duplicate
titles, so this alone finds almost nothing there even when real deals
exist. Checked against real data: **PC components are the same story,
worse** — motherboards, GPUs, RAM, storage, PSUs and cooling all came back
with zero duplicate groups reaching even 2 other listings, in 100-listing
samples of each. Two levers exist for this: `HA_DEAL_THRESHOLD` was
lowered twice (20% -> 15% -> 5%, close to the noise floor between ordinary
seller-to-seller price variation and an actual bargain — expect more
modest markdowns to show up alongside genuine standout deals now), and
`HA_MAX_PAGES_PER_CATEGORY` was raised from 3 to 6 (up to ~600 listings
deep per category instead of ~300) specifically to raise the odds of a
duplicate showing up at all in these sparse categories.

The opposite failure mode also happens — a title too *generic* rather
than too specific — and it produced a real false positive: "PS4
játékok" ("PS4 games") normalizes identically across listings that are
actually bundles of wildly different game counts, 3.6-4x apart in
price, not one product independently priced by different sellers (a
genuine case, like the ROG Ally X deal above, sits under 1.5x). A group
whose prices disagree by more than `HA_MAX_GROUP_SPREAD_RATIO` (default
3.0, max/min) isn't trusted as a market reference at all, even with
enough samples — checked against exactly this real case and the
genuine ones, not picked arbitrarily. This is why the threshold above
was lowered rather than the spread ratio widened: widening it enough to
matter would let that exact false positive back in.

### Retail (árukereső.hu) comparison was tried and dropped

An earlier version also compared listings against the current lowest new
price on árukereső.hu as a fallback for categories used-median can't
cover. It's gone: fetching árukereső.hu directly returns a Cloudflare
managed JS challenge (`cf-mitigated: challenge`, a "Just a moment..."
page) instead of any product markup, for every request, regardless of
network/domain allowlisting. That's not a selector problem plain
`requests`/`BeautifulSoup` scraping can fix — the page never renders
without executing JavaScript and solving the challenge. See git history
(the `retail/` package, since deleted) if reviving this against a
different, actually-scrapable price source.

## Tracked categories

Every hardverapro.hu electronics/computing browse category is tracked by
default — 53 in total, spanning gaming handhelds/consoles, phones/
tablets/wearables, laptops/desktops/servers, every PC component and
peripheral, home theater/hifi, and photo/video
(`hardverapro_arbitrage/categories.py`'s `DEFAULT_SEARCH_URLS`, checked
against a live fetch one by one before being added). Deliberately left
out: each department's own "boltok_szervizek" (shops/services storefront
pages, not individual product listings), "domain" (domain names, not a
physical product), and the whole "egyeb" (misc) department — cars,
fashion, home goods, coupons, services — since that's explicitly the
site's general-classifieds overflow, not "hardver" at all, and this bot's
comparison logic is built for electronics specifically.

## Distance from Budapest / Pest county

Every deal is tagged with a best-effort straight-line distance from
Budapest and a region (`Budapest`, `Pest county`, or `Other`), computed
from the listing's location text against a static table of known
settlements' coordinates (`geo.py`) — not a geocoding API call, on
purpose: the retail comparison above already hit one external site that
turned out to be unusable, so this has no network dependency and nothing
that can start failing if a third-party service changes or blocks
requests. Coverage is necessarily partial (a fixed list of ~100 towns,
not all ~3200 Hungarian settlements) — a location that doesn't match
anything shows as unknown (`—` on the dashboard, `null` in the API)
rather than guessing. A location listing several pickup points (a seller
offering more than one) uses whichever is closest to Budapest, since
that's what actually determines pickup feasibility.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: at minimum set HA_SEARCH_URLS to your saved search URL(s)
```

## Running

```bash
# scrape loop + web dashboard together, one process (recommended)
python -m hardverapro_arbitrage --all

# just one scrape cycle, then exit (good for testing/cron)
python -m hardverapro_arbitrage --once

# just the scrape loop, no dashboard
python -m hardverapro_arbitrage

# just the dashboard, reading whatever's already in the DB
python -m hardverapro_arbitrage --serve
```

`--all` is the normal way to run this: it starts the hourly scrape loop in
a background thread and the dashboard's dev server in the foreground, so
one command gives you both a running bot and something to check from your
phone. Keep that one process alive under whatever you'd normally use —
`screen`/`tmux`, a systemd/Task Scheduler service, `pm2`, a Docker
container — there's nothing here that daemonizes itself.

Deals are always logged to the console. Set `HA_TELEGRAM_BOT_TOKEN` and
`HA_TELEGRAM_CHAT_ID` in `.env` to also get a Telegram message per deal
(see comments in `.env.example` for how to obtain them). Each
(listing, price) pair is only ever notified once — a re-scrape at the
same price won't spam you again, but a further price drop will.

## Remote dashboard

The dashboard (`/`) lists currently-flagged deals, biggest discount first
by default. Click a column header to sort by it instead (discount, price,
category, savings, distance from Budapest, or detected date), click again
to flip direction; the category dropdown filters to one category at a
time. `/api/deals` takes the same `?sort=`, `?dir=` and `?category=` query
params and returns JSON in the same order. There's also `/healthz`. It's
read-only except for one thing — see below — and has no login of its own.

A deal only keeps showing while its listing is still being freshly
re-observed — seen again, un-iced, within the last two poll cycles
(`storage/db.py`'s `get_recent_deals(..., max_listing_age_seconds=...)`).
A flagged deal is a row written once and never revised, so without this a
listing that later goes jegelve or gets sold — the parser then simply
stops producing it as a `Listing` at all, see `_is_iced` above — would
otherwise keep showing as an active deal for the full
`HA_DEALS_LIST_WINDOW_DAYS` regardless. Caught from a real report: a Meta
Quest listing that had gone jegelve after being flagged kept showing as
available.

A **Refresh now** button runs one scrape cycle synchronously and reloads
the page — real and immediate here, since this is a live Python process,
not the static page the Artifact dashboard (next section) is. It blocks
for roughly as long as one scrape cycle (a handful of seconds to under a
minute), and needs `HA_SEARCH_URLS` set.

By default it binds `0.0.0.0:8765`, i.e. every network interface on the
machine running it — that's enough to reach it from another device on the
**same** network. To check deals from your phone while away from home, put
something in front of it that survives the open internet: a WireGuard/
Tailscale tunnel back to that machine (bind to its Tailscale IP, or leave
`0.0.0.0` and just don't forward the port on your router), an SSH `-L`
port-forward, or a reverse proxy that adds auth. Don't port-forward
`HA_WEB_PORT` straight through your router — there's no authentication on
this server.

## Configuration

All of it lives in environment variables, read by
`hardverapro_arbitrage/config.py`; see `.env.example` for the full list
and defaults.

## Data

Prices are stored in a local SQLite file (`HA_DB_PATH`, default
`hardverapro_arbitrage.sqlite3`). Every scrape of every listing is kept as
one row in `observations`, so the price history simply builds up over
time — nothing is ever deleted automatically.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers normalization, market-reference math, deal detection, storage, and
parsing — the parser test fixture is real markup extracted from a live
hardverapro.hu page, not hand-written HTML.
