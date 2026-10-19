"""Tollwood, Munich's summer (Olympiapark Süd) and winter (Theresienwiese) festival — WordPress.

No JSON-LD events, iCal feed or REST endpoint for them (the `post_event` type is not in /wp-json/),
so this reads the festival calendar. The home page links the current season's calendar,
/kalender-winter-2026/ or /kalender-sommer-2027/; between festivals it has no rows.

The calendar is one page with a panel per day (each day twice, for the mobile and desktop
layouts): h4.panel-title "Dienstag 22. Dezember 2026", then one table per hour of tr.mix rows:
td.cell-title, td.cell-category ("Musik", "Kinder", "Zirkus, Tanz & Performances" — the circus and
dance shows, no social dancing), td.cell-location ("Hexenkessel"), td.cell-time
"19:30 bis 22:00 Uhr" and td.cell-details with the detail link (shows with several dates add
/202612221930/; ticketed rows also link to the München Ticket shop).

The calendar says nothing about the music, so each "Musik" act's detail page is read once.
Its div.column-main starts with h1 "Konzert | Hexenkessel", h2 with the act and a heading with
the genre ("New Blues", "Boogie Woogie & Blues der 20er & 30er Jahre", "Rockabilly"), then the
blurb. The genre becomes the event's tag, so `blues_title` keeps the acts billed as blues rather
than every band whose blurb mentions blues somewhere.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text
from ..registry import adapter
from ._html import soup, text

CALENDAR = re.compile(r"/kalender-(winter|sommer)-(\d{4})/?$")
ADDRESS = {"winter": "Theresienwiese, 80336 München", "sommer": "Olympiapark Süd, 80809 München"}


# Between festivals the calendar is empty, which is not a layout change.
@adapter("tollwood", allow_empty=True)
def scrape(source, ctx):
    params = source.get("params", {})
    url = params.get("calendar_url") or calendar_url(ctx.http.text(source["url"]), source["url"])
    if not url:
        return []
    events = parse_calendar(ctx.http.text(url), url)
    details = {}
    for event in events:
        if event.url not in details:
            details[event.url] = parse_detail(ctx.http.text(event.url))
        event.tags, event.description = details[event.url]
    return events


def calendar_url(html: str, base_url: str) -> str | None:
    """The newest season calendar the home page links to (it also links last year's)."""
    found = {}
    for link in soup(html).select("a[href]"):
        href = urljoin(base_url, link["href"])
        m = CALENDAR.search(urlparse(href).path)
        if m:
            found[(m.group(2), m.group(1) == "winter")] = href
    return found[max(found)] if found else None


def parse_calendar(html: str, base_url: str) -> list[Event]:
    """The "Musik" rows of the calendar, once per date and act (without genre or blurb)."""
    m = CALENDAR.search(urlparse(base_url).path)
    address = ADDRESS[m.group(1)] if m else None
    events, seen = [], set()
    for panel in soup(html).select("div.panel-calendar-tile"):
        days = find_dates(text(panel.select_one(".panel-title")))
        if not days:
            continue
        for row in panel.select("tr.mix"):
            if text(row.select_one(".cell-category")) != "Musik":
                continue
            link = next((a["href"] for a in row.select(".cell-details a[href]")
                         if "/veranstaltungen/" in a["href"]), None)
            if not link:
                continue
            start, end = find_time_range(text(row.select_one(".cell-time")))
            event = Event(
                title=text(row.select_one(".cell-title")),
                type="concert",
                start=combine(days[0], start),
                end=combine(days[0], end) if end else None,
                url=urljoin(base_url, link),
                venue=f"Tollwood – {text(row.select_one('.cell-location'))}",
                address=address,
            )
            if (event.url, event.start) not in seen:
                seen.add((event.url, event.start))
                events.append(event)
    return events


def parse_detail(html: str) -> tuple[list[str], str]:
    """([genre], blurb) from an act's detail page."""
    page = soup(html)
    main = page.select_one("div.column-main")
    if main is None:
        meta = page.select_one('meta[name="description"]')
        return [], clean_text(meta["content"]) if meta else ""
    act = main.find("h2")
    genre = act.find_next(["h1", "h2", "h3"]) if act else None
    blurb = " ".join(text(p) for p in main.find_all("p", recursive=False))
    genre_text = text(genre) if genre and main in genre.parents else ""
    return ([genre_text] if genre_text else []), clean_text(f"{genre_text} {blurb}")
