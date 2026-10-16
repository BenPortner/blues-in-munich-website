"""Event model shared by all adapters, the runner and the site builder."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date

EVENT_TYPES = ("class", "workshop", "social", "concert", "festival")


@dataclass
class Event:
    title: str
    type: str  # one of EVENT_TYPES
    # Local Munich time, ISO: "2026-10-21" (all day) or "2026-10-21T20:30"
    start: str
    end: str | None = None
    url: str | None = None
    venue: str | None = None
    address: str | None = None
    description: str = ""
    # Classes: human-readable schedule plus every session date (ISO dates)
    recurrence: str | None = None
    dates: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # Filled in by the runner from the source definition
    source_id: str = ""
    source_name: str = ""
    school_name: str | None = None
    school_url: str | None = None
    id: str = ""

    def finalize(self, source: dict) -> "Event":
        self.title = clean_text(self.title)
        self.description = clean_text(self.description)[:600]
        self.source_id = source["id"]
        self.source_name = source["name"]
        if source.get("kind") == "band" and source["name"].lower() not in self.title.lower():
            self.title = f"{source['name']}: {self.title}"
        if source.get("kind") == "school" and self.type in ("class", "workshop", "social"):
            self.school_name = self.school_name or source["name"]
            self.school_url = self.school_url or source["url"]
        if not self.id:
            key = f"{self.source_id}|{slug(self.title)}|{self.start[:10]}"
            self.id = hashlib.sha1(key.encode()).hexdigest()[:12]
        return self

    @property
    def last_date(self) -> str:
        """The last day this event happens on (ISO date)."""
        candidates = [d[:10] for d in [self.start, self.end, *self.dates] if d]
        return max(candidates)

    def next_date(self, today: date) -> str:
        """The next day (on or after today) this event happens on, for sorting."""
        if self.dates:
            upcoming = [d for d in sorted(self.dates) if d >= today.isoformat()]
            if upcoming:
                return upcoming[0]
        return max(self.start[:10], today.isoformat()) if self.end else self.start[:10]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in known})


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


_TYPE_HINTS = [
    ("festival", r"weekend|weekender|festival|camp\b"),
    ("workshop", r"workshop"),
    ("class", r"\bkurs|\bclass|taster|schnupper"),
    ("social", r"party|social|übungsabend|practice|matinee|record hop|tanzabend|brunch|ball\b"),
    ("concert", r"konzert|concert|live|session|jam\b"),
]


def guess_type(text: str, default: str) -> str:
    lowered = text.lower()
    for event_type, pattern in _TYPE_HINTS:
        if re.search(pattern, lowered):
            return event_type
    return default
