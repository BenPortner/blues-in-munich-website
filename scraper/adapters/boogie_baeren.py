"""Boogie-Bären München e.V. — Contao site.

* /kalender: event list with schema.org microdata, paginated with ?page_e142=N:
  div.event[itemtype=schema.org/Event] > p.location (category) + h3 a (title/link)
  + div[itemprop=description] + time[itemprop=startDate][datetime]
* /training: the weekly class timetable of a cycle ("Zyklus"). One table.trainingsplan
  per cycle, preceded by an h3 "5. Zyklus 2026 vom 14.09. - 01.11.". thead th.room
  names the rooms; each body row is a time slot (td.day with rowspan for the weekday,
  td.time "20:45<br>-<br>22:15"), then one td.training per room with span.title,
  .theme, .trainer, .info (a cell may span several slots). Holidays without
  training are listed under "Training an Feiertagen".

params: listing_url, page_param, max_pages; training_url (false to skip the classes).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text

CATEGORY_TYPES = {"workshop": "workshop", "übungsabend": "social", "clubabend": "social"}
VENUE = "Boogie-Bären Vereinsheim"
ADDRESS = "Gneisenaustraße 16, 80992 München"
WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
WEEKDAYS_EN = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
# One-off cells of the timetable; the calendar already lists them as events
NOT_A_CLASS = re.compile(r"workshop|clubabend|übungsabend", re.I)
MEMBERS_NOTE = ("Club training for members: register for the cycle ({period}). "
                "Newcomers can try classes during the first 3 weeks of a cycle.")


@adapter("boogie_baeren")
def scrape(source, ctx):
    params = source.get("params", {})
    listing = params.get("listing_url", urljoin(source["url"], "kalender"))
    page_param = params.get("page_param", "page_e142")
    events = []
    for page in range(1, params.get("max_pages", 6) + 1):
        html = ctx.http.text(listing, {page_param: page} if page > 1 else None)
        found = parse(html, base_url=listing, today=ctx.today)
        events.extend(found)
        if not found or f"{page_param}={page + 1}" not in html:
            break

    training_url = params.get("training_url", urljoin(source["url"], "training"))
    if training_url:
        events.extend(parse_training(ctx.http.text(training_url), training_url, ctx.today))
    return events


def parse(html, base_url, today=None):
    events = []
    for node in soup(html).select('div.event[itemtype*="schema.org/Event"]'):
        link = node.select_one("h3 a")
        time_el = node.select_one("time[itemprop=startDate]")
        if not link or not time_el:
            continue
        title = text(link)
        category = text(node.select_one("p.location"))
        description = text(node.select_one('[itemprop="description"]'))

        # "17.10.2026–18.10.2026" or "17.10.2026 10:00–16:00"; datetime attr as fallback
        days = find_dates(text(time_el), today=today)
        if not days and len(time_el.get("datetime", "")) >= 10:
            days = [date.fromisoformat(time_el["datetime"][:10])]
        if not days:
            continue
        # Times are also in the link title: "Workshop (Samstag, 17.10.2026 10:00–16:00)"
        t_start, t_end = find_time_range(f"{text(time_el)} {link.get('title', '')}")
        multi_day = len(days) > 1

        external = category.lower() == "extern"
        events.append(Event(
            title=title,
            type=CATEGORY_TYPES.get(category.lower()) or guess_type(f"{title} {description}", "social"),
            start=combine(days[0], t_start),
            end=combine(days[-1], t_end) if (t_end or multi_day) else None,
            url=urljoin(base_url, link["href"]),
            venue=None if external else VENUE,
            address=None if external else ADDRESS,
            description=description,
            tags=[category] if category else [],
        ))
    return events


# --- class timetable ----------------------------------------------------------

def parse_training(html, page_url, today=None):
    doc = soup(html)
    holidays = _holidays(doc)
    events = []
    for table in doc.select("table.trainingsplan"):
        period = _period(text(table.find_previous("h3")))
        if not period:
            continue
        first, last = period
        rooms = [text(th) for th in table.select("thead th.room")]
        grid, cells = _grid(table)
        for row, col, cell, span in cells:
            room = col - 2  # columns: day, time, then one per room
            if "training" not in cell.get("class", []) or not 0 <= room < len(rooms):
                continue
            title = text(cell.select_one("span.title"))
            theme = text(cell.select_one("span.theme"))
            if not title or NOT_A_CLASS.search(f"{title} {theme}"):
                continue
            weekday = _weekday(text(grid.get((row, 0))))
            if weekday is None:
                continue
            t_start, _ = find_time_range(text(grid.get((row, 1))))
            _, t_end = find_time_range(text(grid.get((row + span - 1, 1))))
            info = text(cell.select_one("span.info"))
            # "Start: 17:45 Uhr" / "Ab 18:00 Uhr" moves the start within the slot
            late = re.search(r"(?:start:?|\bab)\s*(\d{1,2}:\d{2})", info, re.I)
            if late:
                t_start = find_time_range(late[1])[0]
            skip = holidays | {(d.month, d.day) for d in _cancellations(info, first.year)}
            dates = [d for d in _weekly(first, last, weekday) if (d.month, d.day) not in skip]
            if not dates:
                continue

            if theme.startswith("(") and theme.endswith(")"):
                theme = theme[1:-1]
            trainers = text(cell.select_one("span.trainer"))
            details = [f"Teachers: {trainers}." if trainers else "", info,
                       MEMBERS_NOTE.format(period=f"{first:%d.%m.}–{last:%d.%m.%Y}")]
            events.append(Event(
                title=_title(title) + (f" · {_title(theme)}" if theme else ""),
                type="class",
                start=combine(dates[0], t_start),
                end=combine(dates[0], t_end) if t_end else None,
                url=page_url,
                venue=f"{VENUE} ({rooms[room]})",
                address=ADDRESS,
                description=" ".join(d for d in details if d),
                recurrence=f"{WEEKDAYS_EN[weekday]} {t_start}–{t_end}" if t_end else WEEKDAYS_EN[weekday],
                dates=[d.isoformat() for d in dates],
                tags=["course block"],
            ))
    return events


def _grid(table):
    """Resolve rowspans: ({(row, col): td}, [(row, col, td, rowspan)] per td)."""
    grid, cells = {}, []
    for row, tr in enumerate(table.select("tbody > tr")):
        col = 0
        for td in tr.find_all("td", recursive=False):
            while (row, col) in grid:
                col += 1
            span = int(td.get("rowspan") or 1)
            for offset in range(span):
                grid[(row + offset, col)] = td
            cells.append((row, col, td, span))
            col += 1
    return grid, cells


def _period(heading):
    """(first, last) day of a cycle from "5. Zyklus 2026 vom 14.09. - 01.11."."""
    year = re.search(r"\b(20\d\d)\b", heading)
    days = find_dates(heading.split("vom", 1)[-1], default_year=int(year[1]) if year else None)
    if len(days) < 2:
        return None
    first, last = days[0], days[-1]
    if last < first:  # cycle runs over New Year
        last = last.replace(year=last.year + 1)
    return first, last


def _holidays(doc):
    """{(month, day)} from the list under "Training an Feiertagen"."""
    for strong in doc.find_all("strong"):
        if "feiertag" in text(strong).lower():
            listing = strong.find_next("ul")
            if listing:
                return {(d.month, d.day) for d in find_dates(text(listing), default_year=2000)}
    return set()


def _cancellations(info, year):
    """Dates from "Entfällt am 30.10" / "entfällt am 11.09. (Season of the Switch)"."""
    found = []
    for m in re.finditer(r"entfällt am\s+((?:\d{1,2}\.\d{1,2}\.?(?:\s*(?:,|\+|und)\s*)?)+)", info, re.I):
        found.extend(find_dates(re.sub(r"(\.\d{1,2})(?![\d.])", r"\1.", m[1]), default_year=year))
    return found


def _weekday(label):
    label = label.lower()
    return next((i for i, name in enumerate(WEEKDAYS) if name in label), None)


def _weekly(first, last, weekday):
    day = first + timedelta(days=(weekday - first.weekday()) % 7)
    while day <= last:
        yield day
        day += timedelta(days=7)


def _title(title):
    """"BLUES OPEN LEVEL" -> "Blues Open Level"; mixed-case words stay as they are."""
    def word(w):
        return "-".join(p.capitalize() for p in w.split("-")) if w.isupper() and len(w) > 1 else w
    return " ".join(word(w) for w in title.split())
