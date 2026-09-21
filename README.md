# Hardverapro Arbitrage Scraper

Polls one or more hardverapro.hu search-result pages every hour, tracks
prices per item over time, and flags listings priced well below that
item's own recent second-hand market price.

## Checklist for when you're back on a machine with real network access

Everything is built and tested except the one thing that couldn't be
verified offline. In order:

1. `pip install -r requirements.txt`
2. `cp .env.example .env` and set `HA_SEARCH_URLS` to your saved search(es)
3. **Fix the selectors** — the one required step, see below
4. `python -m hardverapro_arbitrage --all`
5. Open `http://<that machine>:8765/` — deals appear as the hourly loop finds them

## ⚠️ One step required before this works: fix the selectors

This was built in an environment with **no network access to
hardverapro.hu**, so the HTML parsing selectors in
`hardverapro_arbitrage/scraper/parser.py` (`_SELECTORS`) are best-effort
guesses, never run against the real site. This is the only remaining
blocker — everything else (normalization, pricing, arbitrage detection,
storage, notification, the dashboard) is independent of site markup and
already tested. Once you're on a machine that can reach hardverapro.hu:

```bash
# straight from a live search-results URL...
python -m hardverapro_arbitrage.tools.inspect_html "https://hardverapro.hu/index.php?st=..."

# ...or a page you saved locally (browser -> Save Page As)
python -m hardverapro_arbitrage.tools.inspect_html path/to/saved_page.html
```

It prints exactly what the parser extracted. Compare that to the page in
your browser:

- **0 listings, with a "0 listing cards matched" warning** → the
  `listing_card` selector doesn't match; inspect one ad card in devtools
  and update `_SELECTORS` in `parser.py`.
- **Listings printed, but title/price/url/location look wrong** → same
  fix, just the more specific selector in that dict.

Re-run the tool until its output matches the real page, then it's done —
nothing else in the project needs touching for this.

## How "market price" is computed

There's no external second-hand price API wired in. Instead, the bot
computes its own reference price per item: the **median of all other
recent listings for the same normalized item title**, computed from its
own price-history database. A listing is flagged as a deal once it's
priced `HA_DEAL_THRESHOLD` (default 20%) or more below that median, and
only once at least `HA_MIN_SAMPLES` (default 3) other listings of that
item have been seen — otherwise there's nothing to compare against.

Titles are normalized (`scraper/normalize.py`) by lowercasing, stripping
accents/punctuation, and removing common Hungarian marketplace filler
words ("eladó", "garanciával", "használt", ...) so e.g. "Eladó iPhone 12
128GB garanciával" and "iPhone 12 128 GB" are recognized as the same item.
This is intentionally conservative — it only merges listings whose titles
reduce to an *identical* key, so it never guesses that two differently
named products are the same thing.

If you actually have a specific external price reference in mind (a price
list, another marketplace, etc.) instead of this self-referential
approach, swap out `pricing/market.py` — nothing else needs to change.

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

The dashboard (`/`) lists currently-flagged deals **ranked biggest relative
bargain first** — % below the item's own market reference price, ties
broken by absolute savings. There's also `/api/deals` (JSON, same ranking)
and `/healthz`. It's read-only and has no login of its own.

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
parsing against a synthetic fixture (see the warning above — the fixture
matches the guessed selectors, it isn't real site HTML).
