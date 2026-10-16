"""Bands using the "Mike's Gig Calendar" (mfgigcal) WordPress plugin.

Markup: ul#cal.mfgigcal > li.event: .date (.start-date/.end-date with .day,
.month, .year), .info_block h3 (title), span.time, span.location (venue + address).
Use params.only_city (regex) to keep only gigs in Munich.
"""
from __future__ import annotations

import re
from datetime import date

from ..dates import MONTHS, combine, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text


@adapter("mfgigcal")
def scrape(source, ctx):
    params = source.get("params", {})
    url = params.get("listing_url", source["url"])
    events = parse(ctx.http.text(url), url)
    city = params.get("only_city")
    if city:
        events = [e for e in events if re.search(city, f"{e.venue} {e.address}", re.I)]
    return events


def _date(block):
    try:
        month = MONTHS[text(block.select_one(".month")).rstrip(".").lower()]
        return date(int(text(block.select_one(".year"))), month, int(text(block.select_one(".day"))))
    except (KeyError, ValueError, AttributeError):
        return None


def parse(html, page_url):
    events = []
    for item in soup(html).select("ul.mfgigcal li.event"):
        start_block = item.select_one(".start-date") or item.select_one(".end-date")
        end_block = item.select_one(".end-date")
        start, end = _date(start_block) if start_block else None, _date(end_block) if end_block else None
        title_el = item.select_one(".info_block h3")
        if not start or not title_el:
            continue
        t_start, t_end = find_time_range(text(item.select_one(".time")))
        location = item.select_one(".location")
        lines = [s.strip() for s in location.stripped_strings] if location else []
        venue = lines[0] if lines else None
        # Lines after the venue: optional note, then street + postcode/city
        address_lines = [l for l in lines[1:] if re.search(r"\d", l)]
        notes = [l for l in lines[1:] if l not in address_lines]
        title = text(title_el)
        events.append(Event(
            title=title,
            type=guess_type(f"{title} {' '.join(notes)}", "concert"),
            start=combine(start, t_start),
            end=combine(end, t_end) if end and end != start else None,
            url=page_url,
            venue=venue,
            address=", ".join(address_lines) or None,
            description=" ".join(notes),
        ))
    return events
