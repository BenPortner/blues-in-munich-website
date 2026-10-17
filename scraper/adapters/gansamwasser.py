"""Café Gans am Wasser (beer garden at the Mollsee in Westpark) — Jimdo site.

The free culture programme (organised by LUMA e.V.) lives on Jimdo pages under
/kulturprogramm/: one page per month (/kulturprogramm/programm-<monat>/) plus specials
(/herbstfest/, /kinderprogramm/, /open-stages/), all linked from the overview; the
Christmas market /winterzauber/ gets its own page. Inside #content_area each event is a
run of Jimdo modules, separated by j-hr rules. Two layouts:
  - month and series pages: a.j-calltoaction-link "So, 18. Oktober 2026" (a button linking
    to "/"), h2 "Livemusik: Parkoustics", a j-text "14:00 - 16:00 Uhr", then j-text blurbs;
  - series pages (Open Stages) without date buttons: the dates are lines of a j-text under
    the heading ("Do, 08. Oktober 18:00-20:00 Uhr (ggf. ab 17:30) -> wetterbedingt abgesagt");
  - one-day specials (Herbstfest): the date is a heading at the top ("Samstag, den
    17. Oktober 2026", or a range "27.11.2026 - 01.01.2027"); the sections below have no
    date of their own, only a heading and a j-text time, and take the page's date.
There are no detail pages, so events link to the page they are on.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text

VENUE = "Café Gans am Wasser"
ADDRESS = "Mollsee im Westpark, 81373 München"
SUBPAGE = re.compile(r"^/kulturprogramm/[^/]+/?$")
EXTRA_PAGES = ["/winterzauber/"]
LIVE_MUSIC = re.compile(r"^live\s*musik\s*:\s*", re.I)
CANCELLED = re.compile(r"\babgesagt\b", re.I)
# decoration around headings ("🍁 HERBSTFEST 🍁")
TITLE_TRIM = re.compile(r"^[^\w(„\"]+|[^\w).!?“\"]+$")


@adapter("gansamwasser")
def scrape(source, ctx):
    overview = urljoin(source["url"], "/kulturprogramm/")
    pages = subpages(ctx.http.text(overview), overview)
    pages += [urljoin(source["url"], p) for p in EXTRA_PAGES if urljoin(source["url"], p) not in pages]
    events = []
    for page in pages:
        events.extend(parse(ctx.http.text(page), page, ctx.today))
    return events


def subpages(html, base_url):
    """Programme pages linked from the overview, in order, without duplicates."""
    pages = []
    for a in soup(html).select("#content_area a[href]"):
        if SUBPAGE.match(unquote(a["href"])):
            url = urljoin(base_url, a["href"])
            if url not in pages:
                pages.append(url)
    return pages


def _block(days=None, inherited=False):
    return {"days": days or [], "inherited": inherited, "title": "", "times": None, "text": []}


def parse(html, base_url, today=None):
    content = soup(html).select_one("#content_area")
    if not content:
        return []
    events, page_days, year = [], [], None
    current = _block()

    def flush():
        event = _event(current, base_url)
        if event:
            events.append(event)

    for module in content.select("div.j-module"):
        classes = module.get("class", [])
        body = text(module)
        if "j-callToAction" in classes:
            days = find_dates(body, today=today)
            if days:  # a date button starts the next event
                flush()
                current = _block(days)
            elif body.isdigit() and len(body) == 4:  # a "2026" button heads a series' date list
                year = int(body)
        elif "j-hr" in classes:
            flush()
            current = _block(page_days, inherited=True)
        elif "j-header" in classes:
            days = find_dates(body, today=today)
            if days and not current["days"] or days and current["inherited"]:
                # a date heading: on a one-day special it dates the whole page
                current.update(days=days, inherited=False)
                if not events and not page_days:
                    page_days = days
            elif not current["title"]:
                current["title"] = body
            elif current["times"] is None and find_time_range(body)[0]:
                current["times"] = find_time_range(body)
        elif "j-text" in classes:
            if current["title"] and not current["days"]:
                dated = _dated_lines(module, current, base_url, year, today)
                if dated:
                    events.extend(dated)
                    current = _block()  # the lines were the events; nothing left to flush
                    continue
            if current["times"] is None and find_time_range(body)[0]:
                current["times"] = find_time_range(body)
            elif body:
                current["text"].append(body)
    flush()
    return events


def _dated_lines(module, block, base_url, year, today):
    """One event per line of a date list under a heading (Open Stages)."""
    events = []
    for line in module.get_text("\n").splitlines():
        days = find_dates(line, default_year=year, today=today)
        if days and find_time_range(line)[0] and not CANCELLED.search(line):
            event = _event({**block, "days": days[:1], "times": find_time_range(line)}, base_url)
            if event:
                events.append(event)
    return events


def _event(block, base_url):
    title, days = TITLE_TRIM.sub("", block["title"]), block["days"]
    if not title or not days or CANCELLED.search(title):
        return None
    if block["inherited"] and not block["times"]:
        return None  # an undated section of a special without its own time is a notice, not an event
    live = bool(LIVE_MUSIC.match(title))
    t_start, t_end = block["times"] or (None, None)
    if len(days) > 1 and days[-1] > days[0]:  # "27.11.2026 - 01.01.2027"
        end = days[-1].isoformat()
    else:
        end = combine(days[0], t_end) if t_end else None
    return Event(
        title=LIVE_MUSIC.sub("", title) if live else title,
        type="concert" if live else guess_type(title, "concert"),
        start=combine(days[0], t_start),
        end=end,
        url=base_url,
        venue=VENUE,
        address=ADDRESS,
        description=" ".join(block["text"]),
        tags=["Livemusik"] if live else [],
    )
