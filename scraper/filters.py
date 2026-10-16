"""Decide whether an event is about blues (dance or music).

Filter modes (set per source in sources.yaml):
  blues        keyword in title, description or tags
  blues_title  keyword in title or tags only — for venues (e.g. jazz clubs)
               whose descriptions mention blues in passing
  none         keep everything (source is all-blues, e.g. a blues band)
"""
from __future__ import annotations

import re

from .models import Event

# "Rhythm'n'Blues"/"R&B" is a rock'n'roll-era/pop label, not blues dancing.
_RNB = re.compile(r"rhythm\s*(?:&|and|und|['’`´]?\s*n\s*['’`´]?)\s*blues|\br\s*(?:&|n)\s*b\b", re.I)
_NOISE = re.compile(r"bluesky", re.I)
_BLUES = re.compile(r"blues|slow\s*drag|juke\s*joint", re.I)

MODES = ("blues", "blues_title", "none")


def is_blues(text: str, exclude: list[str] | None = None) -> bool:
    text = _NOISE.sub(" ", _RNB.sub(" ", text))
    for pattern in exclude or []:
        if re.search(pattern, text, re.I):
            return False
    return bool(_BLUES.search(text))


def keep(event: Event, mode: str, exclude: list[str] | None = None) -> bool:
    if mode == "none":
        return True
    fields = [event.title, *event.tags]
    if mode == "blues":
        fields.append(event.description)
    elif mode != "blues_title":
        raise ValueError(f"unknown filter mode '{mode}'; use one of {MODES}")
    return is_blues(" ".join(fields), exclude)
