"""Render data/events.json into a static site in dist/: `python -m web.build`."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Event as ICalEvent
from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.models import Event

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
MUNICH = ZoneInfo("Europe/Berlin")

TYPE_LABELS = {
    "class": "Class", "workshop": "Workshop", "social": "Social",
    "concert": "Concert", "festival": "Festival",
}
FILTERS = [("class", "Classes"), ("workshop", "Workshops"), ("social", "Socials"),
           ("concert", "Concerts"), ("festival", "Festivals")]


def _day(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def fmt_day(d: date, weekday: bool = True) -> str:
    text = f"{d.day} {d.strftime('%b')}"
    return f"{d.strftime('%a')} {text}" if weekday else text


def fmt_time(event: Event) -> str:
    start = event.start[11:16]
    end = event.end[11:16] if event.end and "T" in event.end else ""
    if not start:
        return ""
    if end and (not event.end or event.end[:10] == event.start[:10]):
        return f"{start}–{end}"
    return start


def fmt_span(event: Event) -> str:
    """For multi-day events: '31 Oct – 1 Nov'."""
    if event.end and event.end[:10] != event.start[:10] and not event.dates:
        return f"{fmt_day(_day(event.start), False)} – {fmt_day(_day(event.end), False)}"
    return ""


def view_model(data: dict, today: date) -> dict:
    events = [Event.from_dict(e) for e in data["events"]]
    events = [e for e in events if e.last_date >= today.isoformat()]
    events.sort(key=lambda e: (e.next_date(today), e.start, e.title))

    cards = []
    for e in events:
        upcoming = [_day(d) for d in e.dates if d >= today.isoformat()]
        cards.append({
            "e": e,
            "day": _day(e.next_date(today)),
            "label": TYPE_LABELS.get(e.type, e.type.title()),
            "time": fmt_time(e),
            "span": fmt_span(e),
            "sessions": ", ".join(fmt_day(d, False) for d in upcoming),
            "session_count": len(e.dates),
        })

    months = []
    for (year, month), month_cards in groupby(cards, key=lambda c: (c["day"].year, c["day"].month)):
        month_cards = list(month_cards)
        days = [{"day": d, "label": fmt_day(d), "is_today": d == today, "cards": list(cs)}
                for d, cs in groupby(month_cards, key=lambda c: c["day"])]
        months.append({"label": date(year, month, 1).strftime("%B %Y"), "days": days})

    generated = datetime.fromisoformat(data["generated_at"]).astimezone(MUNICH)
    calendar_json = json.dumps(calendar_events(events), ensure_ascii=False).replace("</", "<\\/")
    counts = {t: sum(1 for c in cards if c["e"].type == t) for t, _ in FILTERS}
    return {
        "months": months,
        "calendar_json": calendar_json,
        "total": len(cards),
        "filters": [(t, label, counts[t]) for t, label in FILTERS if counts[t]],
        "sources": data.get("sources", []),
        "generated": f"{generated.day} {generated.strftime('%b %Y, %H:%M')}",
        "repo_url": os.environ.get("REPO_URL") or (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}" if os.environ.get("GITHUB_REPOSITORY") else None
        ),
    }


def occurrences(e: Event):
    """(start, end) per calendar entry: one per class session, else the event itself. `end` is None
    unless it comes after `start`."""
    for day in e.dates or [e.start[:10]]:
        start = day + e.start[10:]
        end = (day + e.end[10:]) if e.end and e.dates else e.end
        yield start, end if end and end > start else None


def _next_day(iso: str) -> str:
    return (_day(iso) + timedelta(days=1)).isoformat()


def calendar_events(events: list[Event]) -> list[dict]:
    """Entries for the FullCalendar view. Times stay naive Munich wall-clock; the page renders in UTC
    so they show exactly as written. FullCalendar's `end` is exclusive, like iCal's all-day DTEND."""
    items = []
    for e in events:
        for n, (start, end) in enumerate(occurrences(e)):
            all_day = "T" not in start
            if end and all_day != ("T" not in end):  # mixed date/time: stretch to the end of that day
                end = _next_day(end) + ("" if all_day else "T00:00")
            elif end and all_day:
                end = _next_day(end)
            items.append({
                "id": f"{e.id}-{n}",
                "title": e.title,
                "start": start,
                "end": end,
                "allDay": all_day,
                "url": e.url,
                "extendedProps": {
                    "type": e.type,
                    "label": TYPE_LABELS.get(e.type, e.type.title()),
                    "venue": e.venue,
                    "time": fmt_time(e),
                },
            })
    return items


def _ical_dt(iso: str):
    if "T" in iso:
        return datetime.fromisoformat(iso).replace(tzinfo=MUNICH)
    return date.fromisoformat(iso)


def build_ics(data: dict) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Blues in München//events//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Blues in München")
    cal.add("x-wr-timezone", "Europe/Berlin")
    for raw in data["events"]:
        e = Event.from_dict(raw)
        for n, (start, end) in enumerate(occurrences(e)):
            item = ICalEvent()
            item.add("uid", f"{e.id}-{n}@blues-in-munich")
            item.add("summary", e.title)
            item.add("dtstart", _ical_dt(start))
            if end:
                # iCal all-day DTEND is exclusive
                item.add("dtend", _ical_dt(end) if "T" in end else date.fromordinal(_day(end).toordinal() + 1))
            if e.venue or e.address:
                item.add("location", ", ".join(filter(None, [e.venue, e.address])))
            if e.url:
                item.add("url", e.url)
            item.add("description", "\n".join(filter(None, [e.description, e.url, e.school_url])))
            item.add("dtstamp", datetime.now(MUNICH))
            cal.add_component(item)
    cal.add_missing_timezones()
    return cal.to_ical()


def build(data_path: Path, out: Path, today: date) -> None:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("index.html.j2").render(**view_model(data, today))

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HERE / "static", out / "static")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "events.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "events.ics").write_bytes(build_ics(data))
    (out / ".nojekyll").write_text("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "events.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    build(args.data, args.out, args.today or datetime.now(MUNICH).date())
    print(f"built {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
