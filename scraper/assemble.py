"""Build data/events.json from the scraped raw files in data/raw, without scraping:
`python -m scraper.assemble`. `python -m scraper` scrapes first and then runs this.

Raw files hold what each adapter returned, so filters (sources.yaml), title fixes, dedupe and the
Last.fm artist lookups all apply again on every build.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .artists import act_keys, enrich
from .filters import keep
from .models import EVENT_TYPES, Event, slug

log = logging.getLogger("scraper")
ROOT = Path(__file__).resolve().parent.parent


def load_sources(path: Path) -> list[dict]:
    sources = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source ids in sources.yaml")
    return sources


def load_archive(path: Path) -> dict | None:
    """The `archive` block of sources.yaml: which past events stay listed."""
    archive = yaml.safe_load(path.read_text(encoding="utf-8")).get("archive")
    if not archive:
        return None
    return {"since": str(archive["since"]), "types": list(archive.get("types", EVENT_TYPES))}


def is_listed(event: Event, today: str, archive: dict | None) -> bool:
    """Upcoming events, plus past ones the archive keeps."""
    if event.last_date >= today:
        return True
    return bool(archive) and event.type in archive["types"] and event.last_date >= archive["since"]


def load_env_file(path: Path) -> None:
    """Read KEY=value lines from a local .env; real environment variables (e.g. CI secrets) win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep or key.startswith("#"):
            continue
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key.strip(), value)


def load_previous(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"events": [], "sources": []}


def raw_path(raw_dir: Path, source_id: str) -> Path:
    return raw_dir / f"{source_id}.json"


def load_raw(raw_dir: Path, source_id: str) -> dict | None:
    """What the last scrape of a source returned: {"scraped_at", "status", "events"}."""
    path = raw_path(raw_dir, source_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# Words that say what kind of event it is rather than which one: ignored when comparing titles
_FILLER = {
    "session", "jam", "live", "konzert", "concert", "gig", "blues", "band", "night", "abend", "special",
    "open", "offene", "mit", "with", "und", "and", "feat", "the", "der", "die", "das", "im", "in", "am",
    "presents", "prasentiert", "zu", "gast", "guest", "guests", "friends",
}


def _title_words(title: str) -> set[str]:
    title = re.sub(r"['’`´]", "", title)  # "William’s" and "Williams" are the same word
    return {w for w in slug(title).split("-") if len(w) > 1 and w not in _FILLER}


def same_event(a: Event, b: Event) -> bool:
    """The same event listed by two sources under different titles, e.g. "Bernd Bauer Blues Band:
    Stormy Wednesday" and "Session Stormy Wednesday": same day, same place (or, without a venue on
    either side, the same start time), and the shorter title's telling words all in the longer one."""
    if a.start[:10] != b.start[:10]:
        return False
    va, vb = slug(a.venue or ""), slug(b.venue or "")
    if va and vb:
        # sources also name the same place differently ("Groundlift Ammersee Live Studios" vs "Alte
        # Brauerei Stegen"): the same street address counts as the same place
        street_a, street_b = slug((a.address or "").split(",")[0]), slug((b.address or "").split(",")[0])
        same_street = bool(street_a) and street_a == street_b
        if va not in vb and vb not in va and not same_street:
            return False
    elif "T" not in a.start or a.start != b.start:
        return False
    small, big = sorted((_title_words(a.title), _title_words(b.title)), key=len)
    return bool(small) and small <= big


def _fill_gaps(kept: Event, dup: Event) -> None:
    """The first source's listing wins; empty fields are taken from the duplicate."""
    for name in ("end", "venue", "address", "description"):
        if not getattr(kept, name) and getattr(dup, name):
            setattr(kept, name, getattr(dup, name))


def dedupe(events: list[Event]) -> list[Event]:
    """Drop repeats of the same event across sources; first source wins. Catches identical titles on
    the same day, and differently worded ones that `same_event` recognises."""
    seen, result = set(), []
    by_day: dict[str, list[Event]] = {}
    for event in events:
        key = (slug(event.title), event.start[:10])
        if event.id in seen or key in seen:
            continue
        twin = next((e for e in by_day.get(event.start[:10], []) if same_event(e, event)), None)
        if twin:
            seen.update({event.id, key})
            if _title_words(twin.title) < _title_words(event.title):
                # the earlier listing is only a generic one ("Inninger Bluestage 2026" vs. the evening's
                # actual bands): the more specific one replaces it
                _fill_gaps(event, twin)
                result[result.index(twin)] = event
                by_day[event.start[:10]][by_day[event.start[:10]].index(twin)] = event
            else:
                _fill_gaps(twin, event)
            continue
        seen.update({event.id, key})
        by_day.setdefault(event.start[:10], []).append(event)
        result.append(event)
    return result


def source_events(source: dict, raw_dir: Path, previous: dict) -> tuple[list[Event], dict | None, list[Event]]:
    """A source's listed events, status and the events its filter dropped, from its raw file. Before its
    first scrape into data/raw, its events and status from the last events.json stand in; a source never
    scraped has neither."""
    raw = load_raw(raw_dir, source["id"])
    if raw is None:
        events = [Event.from_dict(e) for e in previous.get("events", []) if e["source_id"] == source["id"]]
        status = next((s for s in previous.get("sources", []) if s["id"] == source["id"]), None)
        return events, status and dict(status), []
    events = [Event.from_dict(e).finalize(source) for e in raw["events"]]
    kept = [e for e in events if keep(e, source.get("filter", "blues"), source.get("exclude"))]
    # Name and link may have changed in sources.yaml since the scrape
    status = {**raw["status"], "id": source["id"], "name": source["name"], "url": source["url"],
              "kind": source["kind"]}
    return kept, status, [e for e in events if e not in kept]


def same_artist_gigs(kept: list[Event], dropped: list[Event]) -> list[Event]:
    """Dropped concerts by an act that has a kept concert: one artist, one verdict, whichever venue's
    listing happens to say blues."""
    blues_acts = set().union(*(act_keys(e.title) for e in kept if e.type == "concert"))
    return [e for e in dropped if e.type == "concert" and blues_acts & act_keys(e.title)]


def assemble(sources: list[dict], raw_dir: Path, previous: dict, today: date,
             archive: dict | None = None) -> dict:
    events, statuses, dropped = [], [], []
    for source in sources:
        if not source.get("enabled", True):
            continue
        found, status, filtered_out = source_events(source, raw_dir, previous)
        events.extend(found)
        dropped.extend(filtered_out)
        if status:
            statuses.append(status)

    iso_today = today.isoformat()
    # Sites drop courses once they're over: keep archived ones from the last run (fresh copies win in dedupe)
    listed = {s["id"] for s in statuses}
    past = [e for e in map(Event.from_dict, previous.get("events", []))
            if e.source_id in listed and e.last_date < iso_today]
    # A past gig still vouches for the artist after its site took it down; only past ones, so a gig
    # kept this way can't vouch for itself on the next run
    events.extend(same_artist_gigs(events + past, dropped))
    events.extend(past)
    events = [e for e in dedupe(events) if is_listed(e, iso_today, archive)]
    events.sort(key=lambda e: (e.next_date(today), e.start, e.title))
    for status in statuses:  # count what is actually listed (upcoming + archived, deduplicated)
        status["kept"] = sum(1 for e in events if e.source_id == status["id"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": [e.to_dict() for e in events],
        "sources": statuses,
    }


def build_json(sources_path: Path, raw_dir: Path, out: Path, today: date, http=None,
               dry_run: bool = False) -> dict:
    """Assemble, look up artists and write events.json (or print it, for a dry run)."""
    sources = load_sources(sources_path)
    result = assemble(sources, raw_dir, load_previous(out), today, load_archive(sources_path))
    if dry_run:
        for e in result["events"]:
            print(f"{e['start']:<17} {e['type']:<9} {e['title'][:60]:<60} [{e['source_id']}]")
        print(f"{len(result['events'])} events")
        return result
    if http is None:
        from .http import Http
        http = Http()
    enrich(result["events"], http, os.environ.get("LASTFM_API_KEY"), out.parent / "artists.json",
           sources_path.parent / "highlights.yaml", today)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    log.info("wrote %d events to %s", len(result["events"]), out)
    failed = [s["id"] for s in result["sources"] if s["status"] == "failed"]
    if failed:
        log.warning("failed sources: %s", ", ".join(failed))
    return result


def add_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", type=Path, default=ROOT / "sources.yaml")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw", help="scraped raw files")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "events.json")
    parser.add_argument("--dry-run", action="store_true", help="print events instead of writing")
    parser.add_argument("--today", type=date.fromisoformat, help="override today's date (testing)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_build_args(parser)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_env_file(ROOT / ".env")
    build_json(args.sources, args.raw, args.out, args.today or date.today(), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
