"""Vintage Club München — ASP.NET site without feeds.

* classes.aspx: one `table.Kursstunden` per 4-week course block, preceded by an
  h2 "Kursprogramm Montag, 19. Oktober – Freitag, 13. November 2026". The header
  row (tr.tag) has one colspan cell per weekday with its session dates
  ("21./28. Oktober + 04./11. November"), tr.studio names each column, and
  each body row is a time slot (th "18:45 – 19:45") with one td per column.
* index.aspx / workshops.aspx / parties.aspx: events as h2 title + h5 date.
"""
from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text, text_until

ADDRESS = "Sonnenstraße 12b (Rückgebäude, 3. OG), 80331 München"
WEEKDAYS_EN = {
    "montag": "Mondays", "dienstag": "Tuesdays", "mittwoch": "Wednesdays",
    "donnerstag": "Thursdays", "freitag": "Fridays", "samstag": "Saturdays", "sonntag": "Sundays",
}
REGISTRATION_NOTE = "Advance registration by email required."

DEFAULT_PAGES = [
    {"path": "workshops.aspx", "type": "workshop"},
    {"path": "parties.aspx", "type": "social"},
    {"path": "index.aspx", "type": "social"},
]


@adapter("vintage_club")
def scrape(source, ctx):
    params = source.get("params", {})
    base = source["url"].rstrip("/") + "/"
    classes_url = urljoin(base, params.get("classes_path", "classes.aspx"))
    events = parse_timetable(ctx.http.text(classes_url), classes_url, ctx.today)

    seen = set()
    for page in params.get("event_pages", DEFAULT_PAGES):
        url = urljoin(base, page["path"])
        for event in parse_event_blocks(ctx.http.text(url), url, page["type"], ctx.today):
            key = (event.title.lower(), event.start[:10])
            if key not in seen:  # specials repeat on several pages
                seen.add(key)
                events.append(event)
    return events


# --- course timetable -------------------------------------------------------

def parse_timetable(html, page_url, today=None):
    doc = soup(html)
    descriptions = _course_descriptions(doc)
    events = []
    for table in doc.select("table.Kursstunden"):
        heading = table.find_previous("h2")
        period = find_dates(text(heading), today=today)
        if not period:
            continue
        period_end = period[-1]

        columns = _columns(table, period_end, today)
        for row in table.find_all("tr"):
            slot = row.find("th")
            cells = row.find_all("td", recursive=False)
            if not slot or row.get("class") or not cells:
                continue
            t_start, t_end = find_time_range(text(slot).replace(" – ", "–"))
            for index, cell in enumerate(cells):
                if index >= len(columns):
                    break
                course = _course(cell)
                if not course:
                    continue
                weekday, dates, studio = columns[index]
                if not dates:
                    continue
                name, level, needs_registration = course
                details = [descriptions.get(_level_key(name, level), "")]
                if needs_registration:
                    details.append(REGISTRATION_NOTE)
                events.append(Event(
                    title=f"{name} · {level}" if level else name,
                    type="class",
                    start=combine(dates[0], t_start),
                    end=combine(dates[0], t_end) if t_end else None,
                    url=page_url,
                    venue="Petit Palais" if "petit" in studio.lower() else f"Vintage Club ({studio})",
                    address=None if "petit" in studio.lower() else ADDRESS,
                    description=" ".join(d for d in details if d),
                    recurrence=f"{WEEKDAYS_EN.get(weekday.lower(), weekday)} {t_start}–{t_end}",
                    dates=[d.isoformat() for d in dates],
                    tags=["course block"],
                ))
    return events


def _columns(table, period_end, today):
    """[(weekday, [session dates], studio)] for each td column of the grid."""
    day_row = table.select_one("tr.tag")
    studio_row = table.select_one("tr.studio")
    if not day_row or not studio_row:
        return []
    days = []
    for cell in day_row.find_all("td")[1:]:  # first cell is the "Kurs-termine" label
        lines = [clean_text(s) for s in cell.stripped_strings]
        weekday = lines[0] if lines else ""
        dates = find_dates(" ".join(lines[1:]), default_year=period_end.year, today=today)
        # A December session in a block ending in January belongs to the previous year
        dates = [d.replace(year=d.year - 1) if d > period_end + timedelta(days=7) else d for d in dates]
        days.extend([(weekday, dates)] * int(cell.get("colspan", 1)))
    studios = [text(td) for td in studio_row.find_all("td")]
    return [(w, d, s) for (w, d), s in zip(days, studios)]


def _course(cell):
    """(name, level, needs_registration) from a timetable cell, or None if empty."""
    paragraphs = [text(p) for p in cell.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return None
    name = paragraphs[0]
    needs_registration = name.startswith("**")
    name = name.lstrip("*").strip()
    level = " ".join(paragraphs[1:])
    return name, level, needs_registration


def _course_descriptions(doc):
    """Map "blues|alle level" -> text from the Kursinhalte section.

    Entries look like "<strong>BLUES EXPLORERS = alle Level</strong><br/> Keine ..."
    """
    found = {}
    for strong in doc.find_all("strong"):
        label = text(strong)
        if "=" not in label:
            continue
        name, level = (part.strip() for part in label.split("=", 1))
        body = text(strong.parent).replace(label, "", 1).strip()
        found[f"{name.split()[0].lower()}|{level.lower()}"] = body
    return found


def _level_key(name, level):
    words = re.findall(r"\w+", name.lower())
    style = "blues" if "blues" in words else (words[0] if words else "")
    return f"{style}|{level.lower()}"


# --- workshop / party blocks -------------------------------------------------

def parse_event_blocks(html, page_url, default_type, today=None):
    events = []
    for h2 in soup(html).find_all("h2"):
        h5 = h2.find_next("h5")
        if not h5 or h5.find_previous("h2") is not h2:
            continue  # date heading belongs to a later block
        days = find_dates(text(h5), today=today)
        if not days:
            continue  # "immer am Sonntag!", "XX. November" — no usable date
        title = text(h2)
        description = text_until(h5, ("h1", "h2", "hr"))
        t_start, t_end = find_time_range(f"{text(h5)} {description[:200]}")
        events.append(Event(
            title=title,
            type=guess_type(title, default_type),
            start=combine(days[0], t_start),
            end=combine(days[-1], t_end) if (t_end or len(days) > 1) else None,
            url=page_url,
            venue="Vintage Club",
            address=ADDRESS,
            description=description,
        ))
    return events
