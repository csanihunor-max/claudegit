# Watch Deal Finder

Watches Hungarian marketplaces for used and vintage wristwatches (Soviet
Raketa / Vostok / Poljot / Pobeda / Slava, 1970s–90s Seiko, mid-range Swiss),
sends phone push alerts (via ntfy) for new listings and price drops, and has a small local
dashboard for browsing the candidates.

- **Jófogás**: public search result pages, polled every 15 minutes by default.
- **eBay** (optional): official Browse API, for comparing against active eBay prices.
- **Vatera**: not supported, see [Sources](#sources-and-what-we-found).

```
python main.py run            # scheduled loop
python main.py once           # one pass, then exit (for cron)
python main.py dashboard      # web dashboard on http://127.0.0.1:8080/
python main.py test-notify    # send a test push notification
```

## Setup (laptop, Raspberry Pi or Linux VPS)

Needs Python 3.11+.

```bash
cd watch_deal_finder
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set NTFY_TOPIC (next section)
python main.py test-notify         # should print "sent" and your phone buzzes
python main.py once                # first pass: stores what's listed now, no alerts
python main.py run                 # keep it running; new listings/price drops alert
```

The first pass of each search is **silent** (`silent_first_pass: true`): it
records everything already listed, so you only get alerts for what appears or
gets cheaper after that. Set it to `false` if you want the backlog too.

Data lives in `data/watchfinder.sqlite3`, logs in `logs/watchfinder.log`
(rotated at 1 MB, 5 files kept).

## Phone alerts (ntfy)

Alerts are push notifications through [ntfy](https://ntfy.sh), a free,
open-source notification service. There's no bot and no account: you
subscribe to a topic name in the app, and the tool posts to that topic.

1. Install the **ntfy** app (Google Play / F-Droid / App Store), or open
   https://ntfy.sh/app in a browser for desktop notifications.
2. Make up a long, random topic name. On the public ntfy.sh server, anyone
   who knows the name can read your alerts, so treat it like a password:
   ```bash
   python -c "import secrets; print('watchdeals-' + secrets.token_hex(8))"
   ```
3. In the app tap **+ / Subscribe to topic**, enter that name (server:
   ntfy.sh).
4. Put the same name in `.env`: `NTFY_TOPIC=watchdeals-...`
5. `python main.py test-notify`: your phone should show "✅ Watch Deal Finder".

Tapping a notification opens the listing. 🔥 deals are sent at the highest
priority, so they also come through on a phone set to silent/Do Not Disturb
if you allow that for the ntfy app. The listing thumbnail is attached as an
image.

The alerts contain only listing data (title, price, town, link), nothing
about you. For full privacy you can
[self-host ntfy](https://docs.ntfy.sh/install/) (a Raspberry Pi works) and
set `NTFY_SERVER=https://your-server` and `NTFY_TOKEN=tk_...` in `.env`.

Without `NTFY_TOPIC` the tool still runs; alerts are written to the log
instead.

An alert looks like:

```
🔥 🆕 New · Raketa · 8 000 Ft
Szép állapotban Rakéta karóra
💰 8 000 Ft (~20 €)
📈 resale ref 60 € → est. margin +40 € (+66%)
📍 VIII. kerület, Budapest · Jófogás
```

Price drops show `📉 Price drop` and `↘️ was 12 000 Ft (−33%)`. 🔥 means the
price is at or below 50% (`hot_deal_ratio`) of the search's reference resale
price. The margin is simply reference − price: fees, postage and servicing
are up to you.

## Editing config.yaml

Everything is commented in the file. The parts you'll touch most:

```yaml
searches:
  - name: Raketa                 # shown in alerts and the dashboard filter
    keywords: [raketa]           # each keyword = one search request per pass
    sources: [jofogas, ebay]
    max_price_huf: 30000         # optional: no alerts above this
    reference_price_eur: 60      # optional: enables margin and 🔥
```

- **keywords**: matched case- and accent-insensitively, so `raketa` also
  finds "Rakéta". With `title_must_match: true` (the default) the keyword must
  be in the *title*; the sites also match ad text, which otherwise brings in
  "rakéta" stoves. A multi-word keyword (`seiko 5`) needs all its words in the
  title.
- **max_price_huf**: listings above it are still stored and visible in the
  dashboard (and alert later if the price drops under it), but don't alert.
- **reference_price_eur**: the numbers in the shipped config are placeholders.
  Put in what you actually sell for.
- **blacklist**: words that make a listing ignored everywhere. Also matches
  inside longer words (`gyerek` blocks `gyerekóra`).
- **eur_huf_rate**: fixed rate for the ~EUR figures; update it now and then.
- **poll_interval_minutes**: default 15, minimum 10.
- **request_delay_seconds**: random pause between requests to the same site.
- **sources.jofogas.categories**: which Jófogás categories to search:
  `karorak-` (men's watches, the default), `karorak` (women's watches), or
  `""` (all categories, more noise, but some vintage pieces are listed under
  "Gyűjtemények"). To find another category's slug, open it on jofogas.hu
  and take the part after `/magyarorszag/` in the URL.

Load: each pass makes (number of keywords × number of Jófogás categories)
requests, a few seconds apart. The shipped config makes 14 requests per pass
(a bit over a minute) every 15 minutes, plus a daily robots.txt check.

## Dashboard

```bash
python main.py dashboard                 # http://127.0.0.1:8080/ on this computer
python main.py dashboard --host 0.0.0.0  # reachable from your phone on the same Wi-Fi:
                                         # http://<computer's LAN IP>:8080/
```

It shows active candidates with thumbnail, price (HUF and ~EUR), price
history, estimated margin and when each was first seen. You can filter by
search, source and max price and sort by newest, cheapest or best margin.
The **Interested / Bought / Ignore** buttons mark a listing; click again to
clear. Ignored listings are hidden from the main view and never alert again.
The "Show" menu lists interested, bought, ignored or gone listings. When eBay
is on, choosing a search also shows the median active eBay price for it.

The dashboard has **no login**. Keep it on your home network; don't open
the port to the internet. On a VPS, use an SSH tunnel instead:
`ssh -L 8080:127.0.0.1:8080 you@your-vps`, then open http://127.0.0.1:8080/.

It can run alongside `run`: SQLite is in WAL mode, so reading and writing at
the same time is fine.

## Running it permanently

### Raspberry Pi / Linux (laptop or VPS): systemd (recommended)

Assuming the project is at `/home/pi/claudegit/watch_deal_finder` with the
venv inside it (adjust `User` and paths):

`/etc/systemd/system/watchfinder.service`
```ini
[Unit]
Description=Watch Deal Finder
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/claudegit/watch_deal_finder
ExecStart=/home/pi/claudegit/watch_deal_finder/.venv/bin/python main.py run
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/watchfinder-dashboard.service` (optional)
```ini
[Unit]
Description=Watch Deal Finder dashboard
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/claudegit/watch_deal_finder
ExecStart=/home/pi/claudegit/watch_deal_finder/.venv/bin/python main.py dashboard --host 0.0.0.0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now watchfinder watchfinder-dashboard
journalctl -u watchfinder -f        # or: tail -f logs/watchfinder.log
```

On a VPS, leave out `--host 0.0.0.0` and use the SSH tunnel above.

### Alternative: cron

Use `once` instead of `run` (`crontab -e`):

```cron
*/15 * * * * cd /home/pi/claudegit/watch_deal_finder && flock -n /tmp/watchfinder.lock .venv/bin/python main.py once >/dev/null 2>&1
```

`flock -n` skips a run if the previous one is still going. Output goes to the
log file anyway. `once` exits with status 1 if any search failed.

### Laptop

Just leave `python main.py run` open in a terminal. On macOS/Windows you can
also schedule `python main.py once` every 15 minutes with launchd or Task
Scheduler. Alerts stop while the laptop sleeps, which is where a Pi helps.

### A note on VPS hosting

Jófogás is behind Amazon CloudFront. From the cloud machine this was built
on, requests with a generic `python-requests` User-Agent got HTTP 429, and
the tool's own User-Agent was served normally. Some hosting providers' IP
ranges get blocked outright, though. Run `python main.py once` on a new
VPS and check the log before relying on it. A home connection (laptop or Pi)
is the safest bet.

## Sources and what we found

Checked on 2026-09-23 before writing any scraper.

**Jófogás: supported.**
- robots.txt allows the keyword search pages for ordinary clients. It bans
  AI *training* crawlers (GPTBot, CCBot, ClaudeBot, …), which this tool isn't.
  It disallows price-filter parameters (`min_price`, `max_price`), `&o=`
  pagination and several sort parameters. So the tool reads **page 1 only**
  (36 newest ads per keyword) and applies max price itself. It checks
  robots.txt before every request with a matcher that understands the `*` /
  `$` wildcards (Python's built-in robotparser ignores them).
- Listings are server-rendered: the whole result set is JSON in the page's
  `__NEXT_DATA__` script, so plain `requests` + BeautifulSoup works and no
  JavaScript or Playwright is needed.
- Page 1 only means that, for a busy keyword, older ads fall off the page.
  So when an ad stops appearing, the tool doesn't assume it's gone. After
  6 hours unseen it opens the ad page (a removed ad returns HTTP 410),
  checking at most 5 per pass. When all of a search's results fit on one
  page, a missing ad is marked gone immediately. Gone listings are kept and
  marked, never deleted.

**Vatera: not supported.** Every request, including `robots.txt`, gets an
AWS WAF JavaScript challenge (`HTTP 202`, `x-amzn-waf-action: challenge`,
empty body). Only a real browser running their script gets past it. Getting
around it would mean defeating their bot protection, so the tool doesn't try.
If Vatera ever offers an API or drops the challenge, a source can be added
(see below).

**eBay: official Browse API only.** Off unless configured.
1. Create a developer account at https://developer.ebay.com, go to
   *Application Keys* and create a **Production** keyset.
2. Put the *App ID (Client ID)* and *Cert ID (Client Secret)* in `.env` as
   `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`.
3. Set `sources.ebay.enabled: true` in `config.yaml`, and add `ebay` to the
   `sources` of the searches you want compared.

It searches the Wristwatches category (31387) on eBay.de (EUR) by default.
eBay listings show up in the dashboard, and the median active eBay price per
search appears when you pick that search. eBay alerts are off
(`notify: false`), since eBay is there to compare prices. If `enabled` is
true but the keys are missing, eBay is skipped with a warning. Only EUR and
HUF prices are converted; set `marketplace` to a EUR one.

## What is stored

Only listing data: source, listing ID, title, price, currency, URL,
location (city/region), thumbnail URL, category, first/last seen, and price
history. **No seller names, phone numbers, profiles or other personal data**:
the parsers never read those fields, and a test checks it.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

They cover parsing real saved Jófogás pages (trimmed, seller data removed),
Hungarian price formats (`12 500 Ft`, `12.500 Ft`, `12 500,- Ft`, …), the
blacklist and keyword matching, robots.txt rules, change detection (new,
price drop, gone, reappeared, no duplicate alerts), alert formatting, the
ntfy client and its rate-limit handling, HTTP backoff, the eBay API client, and the dashboard API.
The eBay sample response is hand-written from the API docs, because no keys
were available when this was built.

## Troubleshooting

- **"Jófogás page has no __NEXT_DATA__ block"**: Jófogás changed its page
  structure. Save a search page from your browser and compare it with
  `tests/fixtures/jofogas_*.html`. The parser is `watchfinder/sources/jofogas.py`.
- **HTTP 429 in the log**: the site is rate-limiting. The tool backs off
  (30 s, 60 s, 120 s, honouring `Retry-After`) and tries again next pass. If
  it keeps happening, raise `request_delay_seconds` or the poll interval, or
  see the VPS note above.
- **No alerts**: the first pass is silent by design. Check `max_price_huf`,
  the blacklist, and whether the listing is marked Ignore.
- **No notification on the phone, but `test-notify` says "sent"**: the topic
  in the app and `NTFY_TOPIC` differ (it's case-sensitive), or Android battery
  optimisation is stopping the ntfy app. Allow it to run in the background.
- **ntfy HTTP 429**: ntfy.sh allows bursts of about 60 messages, then one
  every few seconds. The tool waits and retries; this only happens with a
  large backlog (e.g. `silent_first_pass: false`).

## Adding another site

Create `watchfinder/sources/<site>.py` with a class that subclasses `Source`
and implements `search(search) -> SearchResult`, and ideally
`is_gone(listing)`. Register it in `watchfinder/sources/__init__.py` and
`KNOWN_SOURCES` in `config.py`, add a label in `notify.SOURCE_LABELS`, and add
a parser test with a saved sample page. Use the shared `HttpClient`: it
handles the User-Agent, delays, robots.txt and backoff.
