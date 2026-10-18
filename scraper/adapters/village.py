"""Village im Kulturtal Obermühle, Habach ("Home of the Blues") — WordPress, rce-event plugin.

/programm/ lists every upcoming night as div.eventlist_row, in date order:
  - div.eventinfo-date "So.<br>18.<br>Okt." (no year),
  - h5.title with the act (and a link to /programm/?single=<hash>, the detail page),
  - div.event-desc, the first lines of the blurb (usually the genre: "Mischung aus Blues, Rock
    und Soul"), cut off with "...",
  - ul.eventinfo with "Beginn 20:15" and "Eintritt 25€".
Status notes sit in the title between "+++": "+++Entfällt+++Danny Bryant (GBR)",
"+++Verschoben auf den 23.01.27+++UNDER ATTIC", "+++ZUSATZKONZERT+++ Aynsley Lister (GBR)".
Called-off and moved nights are dropped (a moved gig is listed again on its new date); other
notes are stripped from the title.

The list runs about a year ahead, so a missing year is the first one that keeps the dates in
order: "07. Okt." after "02. Sep." is next year's October, not this one's.
"""
from __future__ import annotations

import re
from datetime import date

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text
from ..registry import adapter
from ._html import soup, text

VENUE = "Village Habach"
ADDRESS = "Obermühle 1, 82392 Habach"
NOTE = re.compile(r"\+{2,}([^+]*)\+{2,}")
CALLED_OFF = re.compile(r"entf[äa]llt|verschoben|abgesagt", re.I)


@adapter("village")
def scrape(source, ctx):
    url = source.get("params", {}).get("listing_url") or source["url"].rstrip("/") + "/programm/"
    return parse(ctx.http.text(url), url, ctx.today)


def parse(html, base_url, today=None):
    events, previous = [], None
    for row in soup(html).select("div.eventlist_row"):
        day = _day(text(row.select_one(".eventinfo-date")), previous, today)
        if day is None:
            continue
        previous = day
        heading = row.select_one("h5.title")
        raw_title = text(heading)
        if any(CALLED_OFF.search(note) for note in NOTE.findall(raw_title)):
            continue
        title = clean_text(NOTE.sub(" ", raw_title))
        if not title:
            continue
        info = {text(li.select_one(".eventinfo-title")): text(li.select_one(".eventinfo-value"))
                for li in row.select("ul.eventinfo li")}
        desc = row.select_one(".event-desc:not(.more)")
        link = heading.select_one("a[href]") if heading else None
        events.append(Event(
            title=title,
            type="concert",  # a music club: "Vorsilvesterparty" is a gig too
            start=combine(day, find_time_range(info.get("Beginn", ""))[0]),
            url=link["href"] if link else base_url,
            venue=VENUE,
            address=ADDRESS,
            description=text(desc),
        ))
    return events


def _day(label: str, previous: date | None, today: date | None) -> date | None:
    """ "Do.<br>07.<br>Okt." -> a date no earlier than the row before it."""
    if previous is None:
        days = find_dates(label, today=today)
        return days[0] if days else None
    for year in (previous.year, previous.year + 1):
        days = find_dates(label, default_year=year)
        if days and days[0] >= previous:
            return days[0]
    return None
