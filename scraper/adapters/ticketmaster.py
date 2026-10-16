"""Ticketmaster Discovery API v2 (free key: https://developer.ticketmaster.com).

Searches by genre/classification around a geo point. Skipped when the
API key environment variable is not set.
"""
from __future__ import annotations

import os

from ..models import Event
from ..registry import SkipSource, adapter

API = "https://app.ticketmaster.com/discovery/v2/events.json"
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 7) -> str:
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits, value, even, out = 0, 0, True, []
    while len(out) < precision:
        rng, coord = (lon_range, lon) if even else (lat_range, lat)
        mid = sum(rng) / 2
        value = (value << 1) | (coord >= mid)
        rng[0 if coord >= mid else 1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_BASE32[value])
            bits, value = 0, 0
    return "".join(out)


@adapter("ticketmaster", allow_empty=True)
def scrape(source, ctx):
    params = source.get("params", {})
    key = os.environ.get(params.get("api_key_env", "TICKETMASTER_API_KEY"))
    if not key:
        raise SkipSource("no API key set")
    query = {
        "apikey": key,
        "classificationName": params.get("classification", "Blues"),
        "geoPoint": geohash(*params.get("latlon", [48.1372, 11.5755])),
        "radius": params.get("radius_km", 30),
        "unit": "km",
        "countryCode": "DE",
        "sort": "date,asc",
        "size": 100,
        "locale": "*",
    }
    events = []
    for page in range(params.get("max_pages", 3)):
        data = ctx.http.json(API, {**query, "page": page})
        events.extend(parse(data))
        if page + 1 >= data.get("page", {}).get("totalPages", 0):
            break
    return events


def parse(data: dict) -> list[Event]:
    events = []
    for item in data.get("_embedded", {}).get("events", []):
        start = item.get("dates", {}).get("start", {})
        if not start.get("localDate"):
            continue
        when = start["localDate"]
        if start.get("localTime") and not start.get("timeTBA"):
            when += "T" + start["localTime"][:5]
        venue = (item.get("_embedded", {}).get("venues") or [{}])[0]
        address = ", ".join(filter(None, [
            venue.get("address", {}).get("line1"),
            " ".join(filter(None, [venue.get("postalCode"), venue.get("city", {}).get("name")])),
        ]))
        genres = sorted({
            c.get(level, {}).get("name") for c in item.get("classifications", [])
            for level in ("genre", "subGenre") if c.get(level, {}).get("name") not in (None, "Undefined")
        })
        events.append(Event(
            title=item["name"],
            type="concert",
            start=when,
            url=item.get("url"),
            venue=venue.get("name"),
            address=address or None,
            description=item.get("info") or item.get("pleaseNote") or "",
            tags=genres,
        ))
    return events
