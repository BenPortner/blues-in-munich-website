"""Daily scrape: `python -m scraper` reads sources.yaml and writes data/events.json."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .filters import keep
from .http import Http
from .models import Event, slug
from .registry import Context, SkipSource, get_adapter

log = logging.getLogger("scraper")
ROOT = Path(__file__).resolve().parent.parent


def load_sources(path: Path) -> list[dict]:
    sources = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source ids in sources.yaml")
    return sources


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


def dedupe(events: list[Event]) -> list[Event]:
    """Drop repeats of the same event (same title, same day) across sources; first source wins."""
    seen, result = set(), []
    for event in events:
        key = (slug(event.title), event.start[:10])
        if event.id in seen or key in seen:
            continue
        seen.update({event.id, key})
        result.append(event)
    return result


def collect(sources: list[dict], ctx: Context, previous: dict) -> dict:
    events, statuses = [], []
    for source in sources:
        if not source.get("enabled", True):
            continue
        found, status = run_source(source, ctx, previous.get("events", []))
        events.extend(found)
        statuses.append(status)

    today = ctx.today.isoformat()
    events = [e for e in dedupe(events) if e.last_date >= today]
    events.sort(key=lambda e: (e.next_date(ctx.today), e.start, e.title))
    for status in statuses:  # count what is actually listed (upcoming, deduplicated)
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
    result = collect(sources, ctx, previous)

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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %d events to %s", len(result["events"]), args.out)
    failed = [s["id"] for s in result["sources"] if s["status"] == "failed"]
    if failed:
        log.warning("failed sources: %s", ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
