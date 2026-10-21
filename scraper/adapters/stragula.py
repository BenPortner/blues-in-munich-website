"""Stragula (restaurant with a stage in the Westend) — static events page.

Listing: /events.html. Each item:
  div.event1-2 > div.lunch "Wann: <strong>24.10.2026</strong> Beginn: 20:00 Uhr Eintritt: ...",
  div.lunch "<strong>title</strong> description <a.link band site/YouTube>"
No detail pages, so events link to the listing with a text fragment
(#:~:text=<title>) that scrolls to the event.
"""
from __future__ import annotations

from urllib.parse import quote, urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

ADDRESS = "Bergmannstr. 66, 80339 München"


@adapter("stragula")
def scrape(source, ctx):
    listing = urljoin(source["url"], "/events.html")
    return parse(ctx.http.text(listing), listing, ctx.today)


def parse(html, base_url, today=None):
    events = []
    for node in soup(html).select("div.event1-2"):
        boxes = node.select("div.lunch")
        if len(boxes) < 2:
            continue
        when, info = boxes[0], boxes[1]
        days = find_dates(text(when.find("strong")), today=today)
        title_el = info.find("strong")
        if not days or not title_el:
            continue
        title = text(title_el)
        if title.lower().startswith("geschlossene gesellschaft"):
            continue
        when_text = text(when)
        t_start, t_end = find_time_range(when_text.partition("Beginn:")[2])
        entry = clean_text(when_text.partition("Eintritt:")[2])
        title_el.extract()
        for link in info.select("a.link"):  # band site / YouTube, often empty
            link.extract()
        description = " · ".join(p for p in [text(info), f"Eintritt: {entry}" if entry else ""] if p)
        events.append(Event(
            title=title,
            type=guess_type(title, "concert"),
            start=combine(days[0], t_start),
            end=combine(days[0], t_end) if t_end else None,
            url=f"{base_url}#:~:text={text_fragment(title)}",
            venue="Stragula",
            address=ADDRESS,
            description=description,
        ))
    return events


def text_fragment(value: str) -> str:
    # "-", "&" and "," are fragment syntax and must be escaped too
    return quote(value, safe="").replace("-", "%2D")
