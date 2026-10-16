"""Mister B's — small live bar near the Theresienwiese (WordPress/Uncode one-pager).

Listing: the "programm" section of the home page (https://mister-bs.bar/#programm),
plain server-rendered HTML for the current month. Each gig is an <h2>:
  "Donnerstag 08. Oktober ¦ Elias Prinz & Giangiacomo Rosso ¦ ab 20:00 Uhr"
followed by <p> paragraphs with the description. No year on the page.
"""
from __future__ import annotations

import re

from ..dates import combine, find_dates, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text, text_until

VENUE = "Mister B's"
ADDRESS = "Herzog-Heinrich-Straße 38, 80336 München"
_SEP = re.compile(r"\s*[¦|]\s*")
# Placeholders for nights without a public gig
_SKIP = re.compile(r"geschlossene\s+(veranstaltung|gesellschaft)|private\s+feier|geschlossen\b", re.I)


@adapter("misterbs")
def scrape(source, ctx):
    url = source.get("params", {}).get("listing_url", source["url"])
    return parse(ctx.http.text(url), url, ctx.today)


def parse(html, base_url, today=None):
    page = soup(html)
    section = page.select_one('[data-name="programm"]') or page
    url = base_url.split("#")[0] + "#programm"
    events = []
    for h2 in section.find_all("h2"):
        parts = [p for p in _SEP.split(text(h2)) if p]
        if len(parts) < 2:
            continue  # opening hours etc.
        days = find_dates(parts[0], today=today)
        if not days:
            continue
        title = parts[1]
        if _SKIP.search(title):
            continue
        t_start, _ = find_time_range(" ".join(parts[2:]))
        description = text_until(h2, ("h1", "h2", "h3", "script"))
        events.append(Event(
            title=title,
            type=guess_type(title, "concert"),
            start=combine(days[0], t_start),
            url=url,
            venue=VENUE,
            address=ADDRESS,
            description=description,
        ))
    return events
