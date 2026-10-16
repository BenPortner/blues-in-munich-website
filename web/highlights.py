"""Which events are highlights, from highlights.yaml: chosen sources and types, well-known artists
(found by the scraper, see scraper/artists.py) or big venues."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from scraper.models import Event, slug

VENUE_TYPES = ("concert", "festival")


@dataclass
class Highlights:
    always: dict[str, set[str]]  # source id -> event types that are always highlights
    capacities: dict[str, int]  # slugged venue name or alias -> capacity
    min_capacity: int

    @classmethod
    def load(cls, path: Path) -> "Highlights":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        always = {rule["source"]: set(rule["types"]) for rule in raw.get("always") or []}
        capacities = {}
        for venue in raw.get("venues") or []:
            for name in [venue["name"], *venue.get("match", [])]:
                capacities[slug(name)] = venue["capacity"]
        return cls(always, capacities, raw.get("min_capacity", 400))

    def capacity(self, venue: str | None) -> int | None:
        """Capacity of the longest known name found as whole words in `venue`."""
        if not venue:
            return None
        text = f"-{slug(venue)}-"
        matches = [key for key in self.capacities if f"-{key}-" in text]
        return self.capacities[max(matches, key=len)] if matches else None

    def reason(self, event: Event) -> str | None:
        """Why this event is a highlight (for the badge tooltip), or None if it isn't."""
        if event.type in self.always.get(event.source_id, ()):
            return f"{event.type.title()} by {event.source_name}"
        if event.known_artist and event.type in VENUE_TYPES:
            return f"Well-known artist: {event.known_artist}"
        if event.type in VENUE_TYPES:
            capacity = self.capacity(event.venue)
            if capacity and capacity >= self.min_capacity:
                return f"Big venue: about {capacity:,} people"
        return None

    def unknown_venues(self, events: list[Event]) -> list[str]:
        """Concert and festival venues without a capacity, for extending highlights.yaml."""
        return sorted({e.venue for e in events
                       if e.type in VENUE_TYPES and e.venue and self.capacity(e.venue) is None})
