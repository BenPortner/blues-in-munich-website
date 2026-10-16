"""Generic adapter: schema.org Event objects embedded as JSON-LD.

Works for any venue whose pages carry <script type="application/ld+json">
with @type Event / MusicEvent / DanceEvent / ... . params.urls lists the pages
to read (defaults to the source url).
"""
from __future__ import annotations

import json

from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup


@adapter("jsonld")
def scrape(source, ctx):
    params = source.get("params", {})
    events = []
    for url in params.get("urls", [source["url"]]):
        events.extend(parse(ctx.http.text(url), url, source.get("default_type", "concert")))
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


def parse(html, page_url, default_type="concert"):
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
                end=_local(item.get("endDate")),
                url=item.get("url") or page_url,
                venue=location.get("name") if isinstance(location, dict) else None,
                address=address or None,
                description=clean_text(item.get("description")),
            ))
    return events
