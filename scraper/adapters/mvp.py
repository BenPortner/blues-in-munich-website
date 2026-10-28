"""mvp.de (Münchner Veranstaltungs-Programm) — ticket listing, category "Konzert - Jazz & Blues".

Listing: /muenchen/veranstaltungen/konzert-jazz/ — every date for the next few months on one page.
Each item: div.abl-entry-content with h2.abl-entry-name > a (title, detail link),
  div.location "Schlachthof - Saal, MÜNCHEN",
  p.description "Dienstag,  9. Februar 2027 - Schlachthof - Saal - MÜNCHEN - <title>".
The listing has no start time or street address, so only listings with blues in the title get
their detail page read ("Beginn: 20:00 Uhr", "Adresse: Schlachthof - Saal | Zenettistraße 9, ...").
The category name ("Jazz & Blues") is not kept as a tag: it would make every jazz gig pass the filter.
Titles often end in the town ("... - MÜNCHEN") or a ticket type ("... - Stehplatz"); both are dropped.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from ..dates import combine, find_dates, find_time_range
from ..filters import is_blues
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

LISTING = "/muenchen/veranstaltungen/konzert-jazz/"
TICKET_TYPE = re.compile(r"\s+-\s+(?:Steh|Sitz)pl[aä]tze?$", re.I)


@adapter("mvp")
def scrape(source, ctx):
    listing = urljoin(source["url"], LISTING)
    events = parse(ctx.http.text(listing), listing, ctx.today)
    for event in events:
        if is_blues(event.title):
            add_details(event, ctx.http.text(event.url))
    return events


def parse(html, base_url, today=None):
    events = []
    for card in soup(html).select("div.abl-entry-content"):
        link = card.select_one("h2.abl-entry-name a[href]")
        days = find_dates(text(card.select_one("p.description")), today=today)
        if not link or not days:
            continue
        location = text(card.select_one("div.location"))
        title = _title(text(link), location)
        events.append(Event(
            title=title,
            type=guess_type(title, "concert"),
            start=combine(days[0], None),
            url=urljoin(base_url, link["href"]),
            venue=_venue(location),
        ))
    return events


def add_details(event: Event, html: str) -> None:
    """Start time and street address from the detail page."""
    page = soup(html)
    begin = page.find(string=re.compile(r"Beginn:"))
    if begin:
        t_start, _ = find_time_range(text(begin.parent.parent).partition("Beginn:")[2])
        if t_start:
            event.start = combine(date.fromisoformat(event.start[:10]), t_start)
    label = page.find("b", string=re.compile(r"Adresse:"))
    if label:
        address = text(label.parent).partition("|")[2]
        address = re.split(r"\s+Bahnverbindung", address)[0]
        event.address = _city_case(clean_text(address)) or None


def _title(title: str, location: str) -> str:
    """'Stephan Zinner - Der Teufel ... und ich - MÜNCHEN' -> without the town; drops '- Stehplatz'."""
    town = location.rpartition(",")[2].strip()
    if town and title.lower().endswith(f" - {town.lower()}"):
        title = title[:-len(town) - 3]
    return TICKET_TYPE.sub("", title).strip()


def _venue(value: str) -> str | None:
    """'Schlachthof - Saal, MÜNCHEN' -> 'Schlachthof - Saal' (the town is kept when it isn't Munich)."""
    place, _, town = value.rpartition(",")
    if not place:
        return value or None
    town = _city_case(town.strip())
    return place.strip() if town == "München" else f"{place.strip()}, {town}"


def _city_case(value: str) -> str:
    """mvp.de capitalises the town: 'Zenettistraße 9, 80337 MÜNCHEN' -> '... München'."""
    return re.sub(r"\b[A-ZÄÖÜ]{2,}\b", lambda m: m.group(0).capitalize(), value)
