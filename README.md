# Blues in München

A static site listing **blues events in Munich**: blues dance classes, workshops and socials, plus live blues concerts and sessions. A GitHub Actions job scrapes the sources every morning, commits `data/events.json` and redeploys the site to GitHub Pages.

Visitors can switch between a list and a month / week / year calendar (FullCalendar 6, loaded from jsDelivr only when the calendar is opened), or subscribe to the iCal feed.

```
sources.yaml ──► python -m scraper ──► data/events.json ──► python -m web.build ──► dist/
 (targets)        (adapters + blues filter)  (committed daily)     (index.html, events.ics, events.json)
```

## Sources

The scrape targets are listed in [`sources.yaml`](sources.yaml). Currently enabled:

| Source | Kind | What it gives |
|---|---|---|
| Vintage Club | school | blues courses from the timetable (with session dates), blues workshops/socials |
| Boogie-Bären München | school | blues classes from the training timetable (with session dates), calendar events that mention blues |
| Oksana Pavlova | school | blues workshops announced as news posts (via the WordPress API) |
| Glockenbachwerkstatt | venue | the weekly *Fish'n Blues* concerts |
| Bernd Bauer Blues Band | band | gigs in Munich, incl. the *Stormy Wednesday* open blues session |
| Jazzclub Unterfahrt | venue | gigs billed as blues (title or "Blues" series) |
| Mister B's | venue | live programme of the month, gigs billed as blues |
| SwinginMunich.de | aggregator | swing dance calendar, filtered to events that mention blues |
| IN München | aggregator | city magazine listings whose title or genre says blues (WordPress API) |
| Ticketmaster | aggregator | genre "Blues" within 30 km of Munich (needs a free API key) |
| `manual_events.yaml` | manual | hand-curated events |

Candidates that were checked but can't be scraped yet are listed at the bottom of `sources.yaml`.

Events from swing schools are **filtered to blues**. The filter ignores "Rhythm'n'Blues"/"R&B", which is a rock'n'roll-era label and not blues dancing. Class and workshop cards link to the school as well as the event.

### Adding a source

1. If the site publishes schema.org JSON-LD events, an `.ics` feed, or uses the mfgigcal WordPress plugin, add an entry to `sources.yaml` with `adapter: jsonld`, `ical` or `mfgigcal`. You're done.
2. Otherwise, copy a small adapter such as `scraper/adapters/glockenbachwerkstatt.py`. Register it with `@adapter("name")`, import it in `scraper/adapters/__init__.py`, save a sample page in `tests/fixtures/`, and add a test.
3. Pick a `filter`:
   - `blues`: keyword anywhere
   - `blues_title`: title/tags only, for venues that mention blues in passing
   - `none`: all-blues sources

Then try it with `python -m scraper --dry-run --source <id>`.

To add a one-off event (a festival or an exchange), add it to `manual_events.yaml`.

### Past events

Events that ended on or after `archive.since` in `sources.yaml` (currently 1 Jan 2026) stay listed after they're over, under a collapsed "Past events" section and in the calendar. Add `archive.types` to keep only some event types. Sites take past events off their pages, so each run carries archived events over from the previous `data/events.json`. If a source's page still lists the event, the freshly scraped copy replaces the archived one. Archived events of a source that's disabled or removed drop out.

### Robustness

Each source runs in isolation. If a site is down, or its page suddenly yields no events at all (a layout change), the scraper keeps that source's events from the previous run and marks the source "update failed" in the site footer. Search APIs (Ticketmaster) are the exception: zero results there just means nothing is on, so the source still counts as ok. A source whose API key is missing is skipped.

### Highlights

Some events get a ★ Highlight badge and their own filter chip. [`highlights.yaml`](highlights.yaml) decides which:

- `always`: event types from a given source, e.g. every Boogie-Bären workshop.
- concerts and festivals in big venues: rough capacities and a cutoff (`min_capacity`, currently 400). Venues that aren't listed never count. `python -m web.build` prints the concert venues it couldn't find, so you can add them.

The badge's tooltip says why an event is a highlight.

## Local development

Targets Python 3.15 (the version CI uses).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m scraper --dry-run              # print what would be listed
.venv/bin/python -m scraper                        # write data/events.json
.venv/bin/python -m web.build                      # render dist/
.venv/bin/python -m http.server -d dist 8000       # open http://localhost:8000
```

With conda instead (e.g. on Windows). PyYAML has no Python 3.15 wheel on PyPI yet, so it comes from conda:

```bash
conda create -n blues-in-munich python=3.15 pyyaml=6.0.3 pip
conda activate blues-in-munich
pip install -r requirements.txt
python -m pytest -q
```

To include Ticketmaster locally, copy `.env.example` to `.env` and put your key after `TICKETMASTER_API_KEY=`. The scraper reads `.env` on start; `.env` is git-ignored.

## Deploying to GitHub Pages

1. Push this repo to GitHub (branch `main`).
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. Optional: add a `TICKETMASTER_API_KEY` repository secret. Get a free key at <https://developer.ticketmaster.com>.
4. **Actions → Scrape & deploy → Run workflow** for the first run. After that it runs daily at 04:00 UTC and on every push to `main`.

The workflow runs the tests, scrapes, commits `data/events.json` (so the git history doubles as an event archive), builds `dist/` and deploys it.

To host on S3 instead, run the same steps and replace the two Pages actions with `aws s3 sync dist/ s3://<bucket> --delete`.
