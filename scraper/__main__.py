"""Daily scrape: `python -m scraper` scrapes the sources in sources.yaml into data/raw (one file per
source), then builds data/events.json from them (see scraper/assemble.py). To rebuild events.json
without scraping, run `python -m scraper.assemble`.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from .assemble import (ROOT, add_build_args, build_json, dedupe, load_env_file, load_previous, load_raw,
                       load_sources, raw_path, same_event)
from .http import Http
from .registry import Context, SkipSource, get_adapter

__all__ = ["dedupe", "same_event", "scrape_source", "main", "ROOT"]

log = logging.getLogger("scraper")


def scrape_source(source: dict, ctx: Context, raw_dir: Path, previous: list[dict] = ()) -> dict:
    """Scrape one source into its raw file. On failure, the events from its last scrape stay (or,
    before its first raw file, its events in the last events.json: `previous`)."""
    status = {"id": source["id"], "name": source["name"], "url": source["url"], "kind": source["kind"]}
    old = load_raw(raw_dir, source["id"])
    try:
        scrape = get_adapter(source["adapter"])
        raw = scrape(source, ctx)
        if not raw and source["kind"] != "manual" and not scrape.allow_empty:
            raise RuntimeError("adapter found no events at all — page layout may have changed")
        events = [e.to_dict() for e in raw]
        status.update(status="ok", found=len(raw))
        log.info("%-24s ok: %d found", source["id"], len(raw))
    except SkipSource as exc:
        events = []
        status.update(status="skipped", error=str(exc))
        log.info("%-24s skipped: %s", source["id"], exc)
    except Exception as exc:  # noqa: BLE001 — one broken site must not stop the rest
        events = old["events"] if old else [e for e in previous if e["source_id"] == source["id"]]
        status.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        log.warning("%-24s FAILED (%s); reusing %d events from last scrape", source["id"], exc, len(events))
    path = raw_path(raw_dir, source["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = old["scraped_at"] if old and status["status"] == "failed" else \
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw_file = {"scraped_at": scraped_at, "status": status, "events": events}
    path.write_text(json.dumps(raw_file, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_build_args(parser)
    parser.add_argument("--source", action="append", help="only scrape this source id (repeatable)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_env_file(ROOT / ".env")

    sources = load_sources(args.sources)
    if args.source:
        unknown = set(args.source) - {s["id"] for s in sources}
        if unknown:
            parser.error(f"unknown source id(s): {', '.join(sorted(unknown))}")
    ctx = Context(http=Http(), today=args.today or date.today(), root=args.sources.parent)
    previous = load_previous(args.out)["events"]
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = args.raw
        if args.dry_run:  # scrape into a throwaway copy of data/raw
            raw_dir = Path(tmp) / "raw"
            if args.raw.exists():
                shutil.copytree(args.raw, raw_dir)
        for source in sources:
            if source.get("enabled", True) and (not args.source or source["id"] in args.source):
                scrape_source(source, ctx, raw_dir, previous)
        # Every source's raw file goes into the build, so a partial scrape keeps the others' events
        build_json(args.sources, raw_dir, args.out, ctx.today, ctx.http, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
