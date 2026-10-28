"""ars musica e.V. (Sendling music association) — static programme page.

Listing: /events.php?shortlisting=true (all upcoming events on one page). Each item:
  span.event_categoryelements "Singer-/Songwriter Blues Folk"  (genre line, kept as a tag),
  h2.event_titleelements title, then table.events_parent holding table.events:
  a teaser text ending in "…", rows td.event_date "Do, 29.10.2026, 19:30 Uhr",
  td.event_location, td.event_address; a "Details" link to event_details.php?id=…
Concerts are at their shop stage (Lindwurmstr.), LUISE Kulturzentrum and the Tannengarten.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import Tag

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text


@adapter("arsmusica")
def scrape(source, ctx):
    listing = urljoin(source["url"], "/events.php?shortlisting=true")
    return parse(ctx.http.text(listing), listing, ctx.today, source.get("default_type", "concert"))


def parse(html, base_url, today=None, default_type="concert"):
    events = []
    for heading in soup(html).select("h2.event_titleelements"):
        box = heading.find_next_sibling("table")
        info = box.select_one("table.events") if box else None
        date_el = info.select_one("td.event_date") if info else None
        days = find_dates(text(date_el), today=today) if date_el else []
        if not days:
            continue
        title = text(heading)
        genre = text(heading.find_previous_sibling("span", class_="event_categoryelements"))
        t_start, _ = find_time_range(text(date_el).partition(",")[2].partition(",")[2])
        # the teaser is loose text inside table.events, before its rows
        teaser = clean_text(" ".join(c.get_text(" ") if isinstance(c, Tag) else str(c)
                                     for c in info.children if not (isinstance(c, Tag) and c.name == "tr")))
        details = heading.find_next("a", href=lambda h: h and "event_details.php" in h)
        events.append(Event(
            title=title,
            type=guess_type(f"{genre} {title}", default_type),
            start=combine(days[0], t_start),
            url=urljoin(base_url, details["href"]) if details else base_url,
            venue=text(info.select_one("td.event_location")) or None,
            address=_address(text(info.select_one("td.event_address"))),
            description=teaser.rstrip("… ").strip(),
            tags=[genre] if genre else [],
        ))
    return events


def _address(value: str) -> str | None:
    """'Pfeuferstr. 32,, 81377 München' -> 'Pfeuferstr. 32, 81377 München'."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return ", ".join(parts) or None
