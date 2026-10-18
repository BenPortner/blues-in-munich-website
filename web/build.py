"""Render data/events.json into a static site in dist/: `python -m web.build`."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Event as ICalEvent
from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.models import Event
from web.highlights import Highlights

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
MUNICH = ZoneInfo("Europe/Berlin")
SITE_HOST = "www.bluesinmunich.de"  # must match the CNAME written by .github/workflows/daily.yml

# Operator details for the legal pages, stored reversed so they don't sit in the source as plain text
LEGAL = {"name": "rentroP .W nimajneB"[::-1], "email": "ed.rentrop-nimajneb@retsambew"[::-1]}

TYPE_LABELS = {
    "class": "Class", "workshop": "Workshop", "social": "Social",
    "concert": "Concert",
}
FILTERS = [("class", "Classes"), ("workshop", "Workshops"), ("social", "Socials"),
           ("concert", "Concerts")]
COURSE_HORIZON_MONTHS = 2  # course blocks starting later than this aren't listed yet
# The city's own postcodes; anything else is the region (the place menu: "Munich" / "Munich and region")
MUNICH_POSTCODES = range(80331, 81930)
POSTCODE = re.compile(r"\b(\d{5})\b")


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


def regional(e: Event) -> bool:
    """An event outside Munich, going by the address's postcode (the last five-digit number:
    house numbers come first). Without a postcode it counts as Munich."""
    found = POSTCODE.findall(e.address or "")
    return bool(found) and int(found[-1]) not in MUNICH_POSTCODES


def card(e: Event, today: date, highlights: Highlights) -> dict:
    past = e.last_date < today.isoformat()
    # Past events sit on their first day; their course sessions are all listed
    sessions = [_day(d) for d in e.dates if past or d >= today.isoformat()]
    return {
        "e": e,
        "day": _day(e.start if past else e.next_date(today)),
        "label": TYPE_LABELS.get(e.type, e.type.title()),
        "time": fmt_time(e),
        "span": fmt_span(e),
        "sessions": ", ".join(fmt_day(d, False) for d in sessions),
        "sessions_label": "Sessions" if past else "Upcoming sessions",
        "session_count": len(e.dates),
        "highlight": highlights.reason(e),
        "regional": regional(e),
        # artists.links in highlights.yaml may point elsewhere than Last.fm
        "artists_label": "On Last.fm" if all(a["url"].startswith("https://www.last.fm/") for a in e.artists)
                         else "Artists",
    }


def spotlight_months(today: date) -> tuple[date, date]:
    """First days of this month and the next: the "Upcoming highlights" box covers both."""
    this = today.replace(day=1)
    return this, (this + timedelta(days=32)).replace(day=1)


def group_months(cards: list[dict], today: date) -> list[dict]:
    months = []
    for (year, month), month_cards in groupby(cards, key=lambda c: (c["day"].year, c["day"].month)):
        days = [{"day": d, "label": fmt_day(d), "is_today": d == today, "cards": list(cs)}
                for d, cs in groupby(month_cards, key=lambda c: c["day"])]
        months.append({"label": date(year, month, 1).strftime("%B %Y"), "days": days})
    return months


def months_later(day: date, months: int) -> date:
    """The same day `months` later (the month's last day if it is shorter)."""
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def shown_events(data: dict, today: date) -> list[Event]:
    """The events the site and its calendar feed list: course blocks (classes with session dates)
    only once they start within COURSE_HORIZON_MONTHS, so the next term is listed, not next year's."""
    horizon = months_later(today, COURSE_HORIZON_MONTHS).isoformat()
    events = [Event.from_dict(e) for e in data["events"]]
    return [e for e in events if not (e.type == "class" and e.dates and min(e.dates) > horizon)]


def view_model(data: dict, today: date, highlights: Highlights) -> dict:
    events = shown_events(data, today)
    upcoming = sorted((e for e in events if e.last_date >= today.isoformat()),
                      key=lambda e: (e.next_date(today), e.start, e.title))
    # Archived past events (the runner decides what's kept), newest first
    past = sorted((e for e in events if e.last_date < today.isoformat()),
                  key=lambda e: (e.start, e.title), reverse=True)

    cards = [card(e, today, highlights) for e in upcoming]
    past_cards = [card(e, today, highlights) for e in past]

    generated = datetime.fromisoformat(data["generated_at"]).astimezone(MUNICH)
    calendar_json = json.dumps(calendar_events(past[::-1] + upcoming, highlights),
                               ensure_ascii=False).replace("</", "<\\/")
    counts = {t: sum(1 for c in cards if c["e"].type == t) for t, _ in FILTERS}
    this_month, next_month = spotlight_months(today)
    after = (next_month + timedelta(days=32)).replace(day=1)
    spotlight = [{**c, "day_label": fmt_day(c["day"])} for c in cards if c["highlight"] and c["day"] < after]
    in_town = [c for c in cards if not c["regional"]]

    def chip_counts(match) -> tuple[int, int]:
        """Upcoming events a chip lists without and with the events outside Munich."""
        return sum(1 for c in in_town if match(c)), sum(1 for c in cards if match(c))

    return {
        "spotlight": spotlight,
        "spotlight_label": f"{this_month:%B} & {next_month:%B}",
        "months": group_months(cards, today),
        "past_months": group_months(past_cards, today),
        "past_total": len(past_cards),
        "calendar_json": calendar_json,
        # webcal:// makes calendar apps subscribe (and keep polling) instead of importing a one-off copy
        "webcal_url": f"webcal://{SITE_HOST}/events.ics",
        # Android has no webcal:// handler and the Google Calendar app can't subscribe; its website can
        "gcal_url": "https://calendar.google.com/calendar/render?cid=" + quote(f"webcal://{SITE_HOST}/events.ics", safe=""),
        "total": len(cards),
        "total_counts": chip_counts(lambda c: True),
        # Chips count upcoming events; a type with only past ones still gets a chip
        "filters": [(t, label, chip_counts(lambda c, t=t: c["e"].type == t)) for t, label in FILTERS
                    if counts[t] or any(c["e"].type == t for c in past_cards)],
        # Place menu ("Munich" / "Munich and region"), when some event is out of town
        "region_switch": any(c["regional"] for c in cards + past_cards),
        "region_extra": len(cards) - len(in_town),
        "highlights": chip_counts(lambda c: c["highlight"]),
        "highlight_chip": any(c["highlight"] for c in cards + past_cards),
        # Last.fm's API terms want a credit wherever its data is used
        "lastfm_credit": any(e.artists or e.known_artists for e in events),
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


def calendar_events(events: list[Event], highlights: Highlights | None = None) -> list[dict]:
    """Entries for the FullCalendar view. Times stay naive Munich wall-clock; the page renders in UTC
    so they show exactly as written. FullCalendar's `end` is exclusive, like iCal's all-day DTEND."""
    items = []
    for e in events:
        highlight = bool(highlights and highlights.reason(e))
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
                    **({"highlight": True} if highlight else {}),
                    **({"regional": True} if regional(e) else {}),
                },
            })
    return items


def _ical_dt(iso: str):
    if "T" in iso:
        return datetime.fromisoformat(iso).replace(tzinfo=MUNICH)
    return date.fromisoformat(iso)


def build_ics(data: dict, today: date) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Blues in Munich//events//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Blues in Munich")
    cal.add("x-wr-timezone", "Europe/Berlin")
    for e in shown_events(data, today):
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


def obfuscate_email(addr: str) -> str:
    """Spell the address as "name [at] domain [dot] tld" so it can't be scraped as an email."""
    user, domain = addr.split("@")
    return f"{user} [at] {domain.replace('.', ' [dot] ')}"


def build(data_path: Path, out: Path, today: date, highlights: Highlights | None = None) -> list[str]:
    """Render the site; returns the concert venues missing from highlights.yaml."""
    data = json.loads(data_path.read_text(encoding="utf-8"))
    highlights = highlights or Highlights.load(ROOT / "highlights.yaml")
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]))
    env.filters["obfuscate"] = obfuscate_email
    html = env.get_template("index.html.j2").render(**view_model(data, today, highlights))

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HERE / "static", out / "static")
    (out / "index.html").write_text(html, encoding="utf-8", newline="\n")
    for page, title in (("impressum", "Impressum"), ("datenschutz", "Datenschutzerklärung")):
        (out / f"{page}.html").write_text(
            env.get_template("legal.html.j2").render(page=page, title_de=title, legal=LEGAL), encoding="utf-8", newline="\n")
    (out / "events.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    (out / "events.ics").write_bytes(build_ics(data, today))
    (out / ".nojekyll").write_text("")
    return highlights.unknown_venues([Event.from_dict(e) for e in data["events"]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "events.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    unknown = build(args.data, args.out, args.today or datetime.now(MUNICH).date())
    print(f"built {args.out / 'index.html'}")
    if unknown:
        print(f"{len(unknown)} concert venues have no capacity in highlights.yaml (never highlighted):")
        for venue in unknown:
            print(f"  {venue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
