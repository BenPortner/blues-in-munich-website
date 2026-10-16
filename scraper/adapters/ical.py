"""Generic adapter: an iCalendar (.ics) feed, e.g. a public Google Calendar.

Recurring events (RRULE) are expanded for the next params.horizon_days days.
"""
from __future__ import annotations

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
        for occurrence in starts:
            events.append(Event(
                title=title,
                type=guess_type(title, default_type),
                start=_local(occurrence),
                end=_local(occurrence + duration) if duration else None,
                url=str(comp.get("URL")) if comp.get("URL") else None,
                venue=clean_text(str(comp.get("LOCATION", ""))) or None,
                description=clean_text(str(comp.get("DESCRIPTION", ""))),
            ))
    return events
