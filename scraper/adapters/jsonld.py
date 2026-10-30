"""Generic adapter: schema.org Event objects embedded as JSON-LD.

Works for any venue whose pages carry <script type="application/ld+json">
with @type Event / MusicEvent / DanceEvent / ... . params.urls lists the pages
to read (defaults to the source url).

params.venue, params.address: fallbacks for events whose location is only an @id reference
params.placeholder_time, params.start_time: a start at placeholder_time (a booking system's default,
  e.g. Kilians' "16:00" when the bands start at 21:00) is replaced by start_time
An end time earlier than the start on the same day is taken to be after midnight.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup


@adapter("jsonld")
def scrape(source, ctx):
    params = source.get("params", {})
    events = []
    for url in params.get("urls", [source["url"]]):
        events.extend(parse(ctx.http.text(url), url, source.get("default_type", "concert"), params.get("venue"),
                            params.get("address"), params.get("placeholder_time"), params.get("start_time")))
    return events


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        types = node.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(str(t).endswith("Event") for t in types):
            yield node
        for key in ("@graph", "itemListElement", "item", "subEvent", "event"):
            if key in node:
                yield from _walk(node[key])


def _local(iso: str | None) -> str | None:
    """'2026-10-21T20:30:00+02:00' -> '2026-10-21T20:30' (times are already local)."""
    if not iso:
        return None
    return iso[:16] if "T" in iso else iso[:10]


def _after_midnight(start: str, end: str | None) -> str | None:
    """'…T00:30' ending a '…T21:00' start on the same day is the next morning."""
    if end and "T" in end and end[:10] == start[:10] and end < start:
        return (date.fromisoformat(end[:10]) + timedelta(days=1)).isoformat() + end[10:]
    return end


def parse(html, page_url, default_type="concert", fixed_venue=None, fixed_address=None,
          placeholder_time=None, start_time=None):
    events = []
    for script in soup(html).find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        for item in _walk(data):
            start = _local(item.get("startDate"))
            if not start or not item.get("name"):
                continue
            if placeholder_time and start_time and start[11:] == placeholder_time:
                start = f"{start[:10]}T{start_time}"
            location = item.get("location") or {}
            location = location[0] if isinstance(location, list) and location else location
            address = location.get("address") if isinstance(location, dict) else None
            if isinstance(address, dict):
                address = ", ".join(filter(None, [
                    address.get("streetAddress"),
                    " ".join(filter(None, [address.get("postalCode"), address.get("addressLocality")])),
                ]))
            name = clean_text(item["name"])
            events.append(Event(
                title=name,
                type=guess_type(name, default_type),
                start=start,
                end=_after_midnight(start, _local(item.get("endDate"))),
                url=item.get("url") or page_url,
                venue=(location.get("name") if isinstance(location, dict) else None) or fixed_venue,
                address=address or fixed_address,
                description=clean_text(item.get("description")),
            ))
    return events
