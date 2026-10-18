"""Hep Cat Club, Augsburg (swing dance school by the main station) — WordPress with the ICS Calendar
plugin (r34ics).

The calendar on the home page loads by AJAX: the page carries div.r34ics-ajax-container[data-args]
and a nonce in `r34ics_ajax_obj`; POSTing them to /wp-admin/admin-ajax.php (action r34ics_ajax,
subaction display_calendar) returns the next twelve months at once. Each occurrence is an
li.event with classes "d20261020 t193500", a span.title, span.end_time "– 20:35",
.location and .eventdesc. The feeds are told apart by data-feed-key, named by the legend
(input[data-feed-key] + label: "Regelmäßige Kurse", "Workshops und Events", "Partys und Konzerte",
"Gratis Schnupperkurse"). Multi-day events (festivals) repeat one li per day, each with the whole
span in its class: "d20261211_20261214 all-day" (the end is exclusive).

Weekly classes ("Blues 2 mit Clara", Tuesdays 19:35) become one class per block of weeks, split at
breaks longer than two weeks (Christmas, Easter); other occurrences are single events. There are
no detail pages, so events link to the source url.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from itertools import groupby

from ..dates import combine, find_time_range
from ..models import Event
from ..registry import adapter
from ._html import soup, text

VENUE = "Hep Cat Club"
ADDRESS = "Viktoriastraße 3b, 86150 Augsburg"
AJAX = "/wp-admin/admin-ajax.php"
NONCE = re.compile(r'"r34ics_nonce"\s*:\s*"([0-9a-f]+)"')
DAY = re.compile(r"^d(\d{8})(?:_(\d{8}))?$")  # "d20261020", or a span "d20261211_20261214"
FEED_TYPES = [("schnupper", "class"), ("kurs", "class"), ("workshop", "workshop"), ("event", "workshop"),
              ("part", "social"), ("konzert", "social")]
WEEKDAYS_EN = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
BREAK = timedelta(days=14)  # a longer gap between two classes starts a new block


@adapter("hepcat")
def scrape(source, ctx):
    page = ctx.http.text(source["url"])
    container = soup(page).select_one(".r34ics-ajax-container[data-args]")
    nonce = NONCE.search(page)
    if not container or not nonce:
        raise ValueError("no ICS calendar on the page")
    html = ctx.http.post_text(source["url"].rstrip("/") + AJAX, {
        "action": "r34ics_ajax",
        "r34ics_nonce": nonce[1],
        "subaction": "display_calendar",
        "args": container["data-args"],
        "js_args": container.get("data-js-args", "{}"),
        "ym": container.get("data-r34icsym", ""),
    })
    return parse(html, source["url"])


def feed_types(doc) -> dict[str, str]:
    """data-feed-key -> event type, from the legend's labels."""
    types = {}
    for box in doc.select("input[data-feed-key]"):
        label = doc.select_one(f'label[for="{box.get("id")}"]')
        name = text(label).lower()
        types[box["data-feed-key"]] = next((t for word, t in FEED_TYPES if word in name), "workshop")
    return types


def parse(html, base_url):
    doc = soup(html)
    types = feed_types(doc)
    occurrences = {}  # (title, start, end, feed) -> {first day: (description, last day or None)}
    for li in doc.select("li.event"):
        span = next((m for c in li.get("class", []) if (m := DAY.match(c))), None)
        title_el = li.select_one(".title")
        if not span or not title_el or "cancelled" in title_el.get("class", []):
            continue
        day, last = _day(span[1]), _day(span[2]) if span[2] else None
        if last and "all-day" in li["class"]:
            last -= timedelta(days=1)  # all-day spans end at midnight after the last day
        t_start, t_end = find_time_range(text(li.select_one(".time")))
        key = (text(title_el), t_start, t_end, li.get("data-feed-key", ""))
        occurrences.setdefault(key, {})[day] = (text(li.select_one(".eventdesc")), last if last != day else None)

    events = []
    for (title, t_start, t_end, feed), days in occurrences.items():
        kind = types.get(feed, "workshop")
        dates = sorted(days)
        description = next((d for d, _ in days.values() if d), "")
        if kind == "class" and len(dates) > 1:
            events.extend(_blocks(title, dates, t_start, t_end, description, base_url))
            continue
        for day in dates:
            last = days[day][1]
            events.append(Event(
                title=title,
                type=kind,
                start=combine(day, t_start),
                end=last.isoformat() if last else combine(day, t_end) if t_end else None,
                url=base_url,
                venue=VENUE,
                address=ADDRESS,
                description=description,
            ))
    events.sort(key=lambda e: (e.start, e.title))
    return events


def _day(digits: str) -> date:
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def _runs(dates: list[date], gap: timedelta) -> list[list[date]]:
    """Split sorted dates wherever two neighbours are more than `gap` apart."""
    runs = [[dates[0]]]
    for prev, day in zip(dates, dates[1:]):
        if day - prev > gap:
            runs.append([])
        runs[-1].append(day)
    return runs


def _blocks(title, dates, t_start, t_end, description, base_url):
    for weekday, same_day in groupby(sorted(dates, key=lambda d: (d.weekday(), d)), key=date.weekday):
        for run in _runs(list(same_day), BREAK):
            yield Event(
                title=title,
                type="class",
                start=combine(run[0], t_start),
                end=combine(run[0], t_end) if t_end else None,
                url=base_url,
                venue=VENUE,
                address=ADDRESS,
                description=description,
                recurrence=f"{WEEKDAYS_EN[weekday]} {t_start}–{t_end}" if t_start and t_end else WEEKDAYS_EN[weekday],
                dates=[d.isoformat() for d in run],
            )
