"""Hand-curated events from a YAML file (festivals, one-offs, sites we can't scrape)."""
from __future__ import annotations

import yaml

from ..models import Event
from ..registry import adapter


@adapter("manual")
def scrape(source, ctx):
    path = ctx.root / source.get("params", {}).get("file", "manual_events.yaml")
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    events = []
    for entry in entries:
        entry = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in entry.items()}
        entry.setdefault("type", source.get("default_type", "concert"))
        events.append(Event.from_dict(entry))
    return events
