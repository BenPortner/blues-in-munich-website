"""Generic adapter: an iCalendar (.ics) feed, e.g. a public Google Calendar.

Recurring events (RRULE) are expanded for the next params.horizon_days days. CATEGORIES become tags
and count toward the event type (a "Workshop" category). Venue and address come from
X-APPLE-STRUCTURED-LOCATION (X-TITLE, X-ADDRESS) when the feed has it (WordPress Events Manager does),
otherwise LOCATION is the venue.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar

from ..models import Event, clean_text, guess_type
from ..registry import adapter

MUNICH = ZoneInfo("Europe/Berlin")


@adapter("ical")
def scrape(source, ctx):
    params = source.get("params", {})
    url = params.get("ics_url", source["url"])
    return parse(ctx.http.get(url).content, source.get("default_type", "social"),
                 ctx.today, params.get("horizon_days", 120))


def _local(value) -> str:
    if isinstance(value, datetime):
        if value.tzinfo:
            value = value.astimezone(MUNICH)
        return value.strftime("%Y-%m-%dT%H:%M")
    return value.isoformat()


def parse(raw: bytes, default_type: str, today: date, horizon_days: int = 120) -> list[Event]:
    events = []
    horizon = today + timedelta(days=horizon_days)
    for comp in Calendar.from_ical(raw).walk("VEVENT"):
        start = comp.decoded("DTSTART")
        end = comp.decoded("DTEND") if comp.get("DTEND") else None
        duration = (end - start) if end else None
        starts = [start]
        if comp.get("RRULE"):
            rule = rrulestr(comp["RRULE"].to_ical().decode(), dtstart=start)
            lo = datetime.combine(today, datetime.min.time())
            hi = datetime.combine(horizon, datetime.min.time())
            if isinstance(start, datetime) and start.tzinfo:
                lo, hi = lo.replace(tzinfo=start.tzinfo), hi.replace(tzinfo=start.tzinfo)
            if isinstance(start, datetime):
                starts = rule.between(lo, hi, inc=True)
            else:
                starts = [d.date() for d in rule.between(lo, hi, inc=True)]
        title = clean_text(str(comp.get("SUMMARY", "")))
        tags = _categories(comp)
        venue, address = _location(comp)
        for occurrence in starts:
            events.append(Event(
                title=title,
                type=guess_type(" ".join([title, *tags]), default_type),
                start=_local(occurrence),
                end=_local(occurrence + duration) if duration else None,
                url=str(comp.get("URL")) if comp.get("URL") else None,
                venue=venue,
                address=address,
                description=clean_text(str(comp.get("DESCRIPTION", ""))),
                tags=tags,
            ))
    return events


def _categories(comp) -> list[str]:
    value = comp.get("CATEGORIES")
    props = value if isinstance(value, list) else [value] if value is not None else []
    # Events Manager escapes "&" in category names ("Musik &amp; Tanz")
    return [clean_text(html.unescape(str(c))) for prop in props for c in prop.cats]


def _location(comp) -> tuple[str | None, str | None]:
    """(venue, address). 'Schwanthalerstr. 80, München, 80336, Deutschland' keeps its parts but the country."""
    structured = comp.get("X-APPLE-STRUCTURED-LOCATION")
    if structured is not None and structured.params.get("X-TITLE"):
        parts = [p.strip() for p in structured.params.get("X-ADDRESS", "").split(",")]
        address = ", ".join(p for p in parts if p and p not in ("Deutschland", "Germany"))
        return clean_text(structured.params["X-TITLE"]), clean_text(address) or None
    return clean_text(str(comp.get("LOCATION", ""))) or None, None
