"""Artist popularity from Last.fm (free key: https://www.last.fm/api/account/create).

For each concert, guesses artist names from the title and looks them up with `artist.getInfo`.
If the best-known one has at least `artists.min_listeners` listeners (highlights.yaml), its name
goes on the event as `known_artist`. Listener counts themselves are not published.

Lookups are cached in data/artists.json (git-ignored; CI keeps it in the Actions cache) and
refreshed after REFRESH_DAYS, so a daily run only asks about new names. Without an API key,
cached values are used as they are; with no cache either, no event gets a known artist.

Last.fm's API terms ask for a "powered by AudioScrobbler" credit and for written approval
before pages using the data go public: the site shows the credit whenever an event has a
known artist, and the feature stays off until LASTFM_API_KEY is set.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import requests
import yaml

from .models import slug

log = logging.getLogger("scraper")

API = "https://ws.audioscrobbler.com/2.0/"
TYPES = ("concert", "festival")
REFRESH_DAYS = 30
MAX_LOOKUPS = 200  # per run; Last.fm asks for at most a few requests a second

_QUOTES = "\"'„“”‚‘’«»"
# "Artist – Programme title" / "Artist (support: …)": only the part before is a name
_TAIL = re.compile(r"\s+[–—-]\s+|\s*[(|]")
# "Series: Artist + Artist" or "Artist: what's on": either side may hold names
_COLON = re.compile(r"\s*:\s+")
# Separate acts on one bill
_ACTS = re.compile(r"\s+(?:\+|feat\.?|ft\.?|featuring|mit|with|vs\.?)\s+|\s*[,/]\s+", re.I)
# Duos, or one band name with "&" in it ("B.B. & The Blues Shacks"): tried after the whole act
_DUO = re.compile(r"\s+(?:&|und|and)\s+", re.I)
_ENSEMBLE = re.compile(r"\s+(?:(?:&|and|und)\s+(?:his\s+|seine\s+)?band|trio|quartet|quartett|quintet|group|gruppe|band)$",
                       re.I)
# Bits of titles that are events, not artists
_NOT_A_NAME = re.compile(
    r"^\d+\.|\b\d{4}\b|festival|konzert|concert|bluesnacht|bluestage|blues night|session|\blive\b|"
    r"unplugged|frühschoppen|matinee|\bjam\b|open stage|tribute", re.I)
_GENERIC = {"friends", "band", "guests", "special-guests", "special-guest", "support", "trio", "and-friends"}


@dataclass
class Artist:
    name: str
    listeners: int


def _variants(name: str, ignore: set[str]) -> list[str]:
    """The name, then without a trailing "Band"/"Trio"/"& Band" (Last.fm often lists the leader)."""
    name = name.strip(_QUOTES + " .!?")
    out = []
    for variant in (name, _ENSEMBLE.sub("", name)):
        key = slug(variant)
        if (len(key) >= 3 and key not in _GENERIC and key not in ignore
                and not _NOT_A_NAME.search(variant) and variant not in out):
            out.append(variant)
    return out


def _first(lookup: Callable[[str], Artist | None], names: list[str]) -> Artist | None:
    for name in names:
        if hit := lookup(name):
            return hit
    return None


def find_artists(title: str, lookup: Callable[[str], Artist | None], ignore: set[str] = frozenset()) -> list[Artist]:
    """Artists Last.fm knows among the acts in a concert title."""
    head = _TAIL.split(title, maxsplit=1)[0]
    found = []
    for part in _COLON.split(head):
        for act in _ACTS.split(part):
            hit = _first(lookup, _variants(act, ignore))
            if hit:
                found.append(hit)
                continue
            duo = _DUO.split(act)
            if len(duo) > 1:
                # Single words ("Johnny" of "Johnny & The Yooahoos") too often match someone else
                duo = [p for p in duo if len(p.split()) > 1]
                found.extend(h for h in (_first(lookup, _variants(p, ignore)) for p in duo) if h)
    return found


class LastFm:
    """Cached `artist.getInfo` lookups. Returns None for names Last.fm doesn't know."""

    def __init__(self, http, api_key: str | None, cache: dict, today: date,
                 aliases: dict[str, str] | None = None, max_lookups: int = MAX_LOOKUPS):
        self.http = http
        self.api_key = api_key
        self.cache = cache
        self.today = today
        self.aliases = {slug(k): v for k, v in (aliases or {}).items()}
        self.budget = max_lookups
        self.used: set[str] = set()
        self.lookups = 0

    def __call__(self, name: str) -> Artist | None:
        name = self.aliases.get(slug(name), name)
        key = slug(name)
        self.used.add(key)
        entry = self.cache.get(key)
        stale = not entry or date.fromisoformat(entry["checked"]) < self.today - timedelta(days=REFRESH_DAYS)
        if stale and self.api_key and self.budget > 0:
            self.budget -= 1
            try:
                entry = self._fetch(name)
            except Exception as exc:  # noqa: BLE001 — keep cached values, try again tomorrow
                log.warning("last.fm lookup failed (%s); using cached artist data for the rest", exc)
                self.budget = 0
            else:
                self.cache[key] = entry
                self.lookups += 1
        if entry and entry["name"]:
            return Artist(entry["name"], entry["listeners"])
        return None

    def _fetch(self, name: str) -> dict:
        params = {"method": "artist.getInfo", "artist": name, "autocorrect": 0,
                  "api_key": self.api_key, "format": "json"}
        try:
            data = self.http.json(API, params)
        except requests.HTTPError as exc:
            data = _error_body(exc)
        checked = self.today.isoformat()
        if data.get("error") == 6:  # artist not found
            return {"name": None, "listeners": 0, "checked": checked}
        if "error" in data:
            raise RuntimeError(f"error {data['error']}: {data.get('message')}")
        artist = data["artist"]
        if slug(artist["name"]) != slug(name):  # exact names only, no fuzzy matches
            return {"name": None, "listeners": 0, "checked": checked}
        return {"name": artist["name"], "listeners": int(artist["stats"]["listeners"]), "checked": checked}


def _error_body(exc: requests.HTTPError) -> dict:
    """Last.fm sends errors as JSON, sometimes with a 4xx status."""
    try:
        data = exc.response.json()
    except Exception:  # noqa: BLE001
        raise exc from None
    if "error" not in data:
        raise exc
    return data


def load_settings(path: Path) -> dict:
    """The `artists` block of highlights.yaml."""
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
    raw = raw.get("artists") or {}
    return {"min_listeners": raw.get("min_listeners", 50000),
            "ignore": {slug(n) for n in raw.get("ignore") or []},
            "aliases": raw.get("aliases") or {}}


def enrich(events: list[dict], http, api_key: str | None, cache_path: Path, settings_path: Path,
           today: date) -> None:
    """Set `known_artist` on concert events (dicts, as written to events.json)."""
    settings = load_settings(settings_path)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    lastfm = LastFm(http, api_key, cache, today, settings["aliases"])
    if not api_key:
        log.info("no LASTFM_API_KEY set: using cached artist data only")
    for event in events:
        if event["type"] not in TYPES:
            continue
        found = find_artists(event["title"], lastfm, settings["ignore"])
        best = max(found, key=lambda a: a.listeners, default=None)
        event["known_artist"] = best.name if best and best.listeners >= settings["min_listeners"] else None
    # Keep only names that are still on the bill, so the file doesn't grow forever
    kept = {k: v for k, v in sorted(cache.items()) if k in lastfm.used}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.info("artists: %d looked up on last.fm, %d events with a well-known artist", lastfm.lookups,
             sum(1 for e in events if e.get("known_artist")))
