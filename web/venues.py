"""Venue capacities from venues.yaml, used to mark concerts in big venues as highlights."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from scraper.models import Event, slug

HIGHLIGHT_TYPES = ("concert", "festival")


@dataclass
class Venues:
    capacities: dict[str, int]  # slugged venue name or alias -> capacity
    min_capacity: int

    @classmethod
    def load(cls, path: Path) -> "Venues":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        capacities = {}
        for venue in raw.get("venues") or []:
            for name in [venue["name"], *venue.get("match", [])]:
                capacities[slug(name)] = venue["capacity"]
        return cls(capacities, raw.get("highlight_min_capacity", 400))

    def capacity(self, venue: str | None) -> int | None:
        """Capacity of the longest known name found as whole words in `venue`."""
        if not venue:
            return None
        text = f"-{slug(venue)}-"
        matches = [key for key in self.capacities if f"-{key}-" in text]
        return self.capacities[max(matches, key=len)] if matches else None

    def is_highlight(self, event: Event) -> bool:
        capacity = self.capacity(event.venue)
        return event.type in HIGHLIGHT_TYPES and capacity is not None and capacity >= self.min_capacity

    def unknown(self, events: list[Event]) -> list[str]:
        """Concert and festival venues without a capacity, for extending venues.yaml."""
        return sorted({e.venue for e in events
                       if e.type in HIGHLIGHT_TYPES and e.venue and self.capacity(e.venue) is None})
