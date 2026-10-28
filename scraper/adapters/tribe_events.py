"""Generic adapter: WordPress sites running The Events Calendar ("tribe" events).

Reads its REST API, /wp-json/tribe/events/v1/events (upcoming events, oldest first):
  title, description (HTML), start_date / end_date "2026-11-10 20:00:00" (local time),
  all_day, url, cost, venue {venue, address, zip, city}, tags [{name}], categories [{slug}].
Tags become event tags, so `filter: blues_title` also keeps events tagged e.g. "BluesJazz".

params.categories: category slugs to read (default: all events)
params.max_pages:  pages of 50 events to read (default 5)
params.venue_prefix: put before room names, e.g. "Pasinger Fabrik" -> "Pasinger Fabrik – Wagenhalle"
params.venue, params.address: fixed venue and address for single-hall sites (their own are often
                   missing or garbled)
"""
from __future__ import annotations

import html
import json
from urllib.parse import urljoin

from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

PER_PAGE = 50


@adapter("tribe_events")
def scrape(source, ctx):
    api = urljoin(source["url"], "/wp-json/tribe/events/v1/events")
    params = source.get("params", {})
    query = {"per_page": PER_PAGE}
    if params.get("categories"):
        query["categories"] = ",".join(params["categories"])
    events = []
    for page in range(1, params.get("max_pages", 5) + 1):
        data = json.loads(ctx.http.text(api, {**query, "page": page}))
        events.extend(parse(data, source.get("default_type", "concert"), params.get("venue_prefix"),
                            params.get("venue"), params.get("address")))
        if page >= data.get("total_pages", 1):
            break
    return events


def parse(data: dict, default_type: str = "concert", venue_prefix: str | None = None,
          fixed_venue: str | None = None, fixed_address: str | None = None) -> list[Event]:
    events = []
    for item in data.get("events", []):
        title = clean_text(html.unescape(item["title"]))
        start, end = _local(item["start_date"], item.get("all_day")), _local(item.get("end_date"), item.get("all_day"))
        venue = item.get("venue") or {}  # [] when the event has no venue
        cost = clean_text(html.unescape(item.get("cost") or ""))
        description = " · ".join(p for p in [text(soup(item.get("description") or "")),
                                             f"Eintritt: {cost}" if cost else ""] if p)
        events.append(Event(
            title=title,
            type=guess_type(title, default_type),
            start=start,
            end=end if end != start else None,
            url=item.get("url"),
            venue=fixed_venue or _venue(clean_text(html.unescape(venue.get("venue") or "")), venue_prefix),
            address=fixed_address or _address(venue),
            description=description,
            tags=[clean_text(html.unescape(t["name"])) for t in item.get("tags", [])],
        ))
    return events


def _local(value: str | None, all_day: bool = False) -> str | None:
    """'2026-11-10 20:00:00' -> '2026-11-10T20:00' ('2026-11-10' for all-day events)."""
    if not value:
        return None
    return value[:10] if all_day else value[:16].replace(" ", "T")


def _venue(name: str, prefix: str | None) -> str | None:
    if prefix and name and not name.startswith(prefix):
        return f"{prefix} – {name}"
    return name or prefix


def _address(venue: dict) -> str | None:
    city = " ".join(filter(None, [venue.get("zip"), venue.get("city")]))
    return ", ".join(filter(None, [venue.get("address"), city])) or None
