"""Daily scrape: `python -m scraper` reads sources.yaml and writes data/events.json."""
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

from .artists import enrich
from .filters import keep
from .http import Http
from .models import EVENT_TYPES, Event, slug
from .registry import Context, SkipSource, get_adapter

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


def run_source(source: dict, ctx: Context, previous: list[dict]) -> tuple[list[Event], dict]:
    """Scrape one source. On failure, fall back to its events from the last run."""
    status = {"id": source["id"], "name": source["name"], "url": source["url"], "kind": source["kind"]}
    try:
        scrape = get_adapter(source["adapter"])
        raw = scrape(source, ctx)
        if not raw and source["kind"] != "manual" and not scrape.allow_empty:
            raise RuntimeError("adapter found no events at all — page layout may have changed")
        events = [e.finalize(source) for e in raw]
        events = [e for e in events if keep(e, source.get("filter", "blues"), source.get("exclude"))]
        status.update(status="ok", found=len(raw), kept=len(events))
        log.info("%-24s ok: %d found, %d blues", source["id"], len(raw), len(events))
    except SkipSource as exc:
        events = []
        status.update(status="skipped", error=str(exc))
        log.info("%-24s skipped: %s", source["id"], exc)
    except Exception as exc:  # noqa: BLE001 — one broken site must not stop the rest
        events = [Event.from_dict(e) for e in previous if e["source_id"] == source["id"]]
        status.update(status="failed", error=f"{type(exc).__name__}: {exc}", kept=len(events))
        log.warning("%-24s FAILED (%s); reusing %d events from last run", source["id"], exc, len(events))
    return events, status


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


def collect(sources: list[dict], ctx: Context, previous: dict, archive: dict | None = None) -> dict:
    events, statuses = [], []
    for source in sources:
        if not source.get("enabled", True):
            continue
        found, status = run_source(source, ctx, previous.get("events", []))
        events.extend(found)
        statuses.append(status)

    today = ctx.today.isoformat()
    # Sites drop courses once they're over: keep archived ones from the last run (fresh copies win in dedupe)
    ran = {s["id"] for s in statuses}
    events.extend(e for e in map(Event.from_dict, previous.get("events", []))
                  if e.source_id in ran and e.last_date < today)
    events = [e for e in dedupe(events) if is_listed(e, today, archive)]
    events.sort(key=lambda e: (e.next_date(ctx.today), e.start, e.title))
    for status in statuses:  # count what is actually listed (upcoming + archived, deduplicated)
        status["kept"] = sum(1 for e in events if e.source_id == status["id"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": [e.to_dict() for e in events],
        "sources": statuses,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT / "sources.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "events.json")
    parser.add_argument("--source", action="append", help="only run this source id (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="print events instead of writing")
    parser.add_argument("--today", type=date.fromisoformat, help="override today's date (testing)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_env_file(ROOT / ".env")

    sources = load_sources(args.sources)
    order = {s["id"]: i for i, s in enumerate(sources)}
    if args.source:
        unknown = set(args.source) - {s["id"] for s in sources}
        if unknown:
            parser.error(f"unknown source id(s): {', '.join(sorted(unknown))}")
        sources = [s for s in sources if s["id"] in args.source]

    ctx = Context(http=Http(), today=args.today or date.today(), root=args.sources.parent)
    previous = load_previous(args.out)
    result = collect(sources, ctx, previous, load_archive(args.sources))

    if args.dry_run:
        for e in result["events"]:
            print(f"{e['start']:<17} {e['type']:<9} {e['title'][:60]:<60} [{e['source_id']}]")
        print(f"{len(result['events'])} events")
        return 0

    if args.source:  # partial run: keep other sources' events and statuses from the last run
        ran = set(args.source)
        result["events"] = sorted(
            [e for e in previous["events"] if e["source_id"] not in ran] + result["events"],
            key=lambda e: (Event.from_dict(e).next_date(ctx.today), e["start"], e["title"]),
        )
        result["sources"] = sorted(
            [s for s in previous["sources"] if s["id"] not in ran and s["id"] in order] + result["sources"],
            key=lambda s: order[s["id"]],
        )

    enrich(result["events"], ctx.http, os.environ.get("LASTFM_API_KEY"), args.out.parent / "artists.json",
           args.sources.parent / "highlights.yaml", ctx.today)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    log.info("wrote %d events to %s", len(result["events"]), args.out)
    failed = [s["id"] for s in result["sources"] if s["status"] == "failed"]
    if failed:
        log.warning("failed sources: %s", ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
