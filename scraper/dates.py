"""Parsing helpers for the German date/time formats found on Munich event pages.

Handles e.g. "Samstag, 17. Oktober 2026", "21./28. September + 05./12. Oktober",
"Freitag, 23.10. – Sonntag, 25.10.2026", "17.10.2026–18.10.2026", "21.10.".
"""
from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "jänner": 1,
    "feb": 2, "februar": 2, "february": 2,
    "mär": 3, "märz": 3, "maerz": 3, "mrz": 3, "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dezember": 12, "dec": 12, "december": 12,
}
# Words that may sit between a day number and its month without breaking the link
_CONNECTORS = {"und", "and", "bis", "to"}

_TOKEN = re.compile(
    r"(?P<num>\d{1,2})\.(?:(?P<mon>\d{1,2})\.(?P<yr>\d{4}|\d{2}(?!\d))?)?"
    r"|(?P<year>\b\d{4}\b)"
    r"|(?P<word>[A-Za-zÄÖÜäöüß]+)"
)


def find_dates(text: str, default_year: int | None = None, today: date | None = None) -> list[date]:
    """Return all dates mentioned in `text`, in order of appearance.

    Years missing from the text come from a later year in the same text,
    then `default_year`, then the next occurrence relative to `today`.
    """
    found: list[list] = []  # [day, month, year|None]
    pending: list[int] = []
    for m in _TOKEN.finditer(text):
        if m.group("num"):
            day = int(m.group("num"))
            if m.group("mon"):
                yr = m.group("yr")
                year = None if not yr else int(yr) + (2000 if len(yr) == 2 else 0)
                found.append([day, int(m.group("mon")), year])
                pending = []
            else:
                pending.append(day)
        elif m.group("year"):
            # Apply the year backwards; stepping back over a month wrap
            # ("14. Dezember – 15. Januar 2027") means the previous year.
            year, later_month = int(m.group("year")), 13
            for item in reversed(found):
                if item[2] is not None:
                    break
                if item[1] > later_month:
                    year -= 1
                item[2], later_month = year, item[1]
        else:
            word = m.group("word").lower()
            month = MONTHS.get(word)
            if month:
                found.extend([d, month, None] for d in pending)
                pending = []
            elif word not in _CONNECTORS:
                pending = []

    result = []
    for day, month, year in found:
        if year is None:
            year = default_year or _infer_year(day, month, today or date.today())
        try:
            result.append(date(year, month, day))
        except ValueError:
            continue  # e.g. "Übungsabend 10.26" is not a date
    return result


def _infer_year(day: int, month: int, today: date) -> int:
    """Pick the year that puts day.month closest to the future (allowing ~2 months back)."""
    for year in (today.year, today.year + 1):
        try:
            if date(year, month, day) >= today - timedelta(days=60):
                return year
        except ValueError:
            continue
    return today.year + 1


_TIME_RANGE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(?:Uhr)?\s*(?:[–—-]|bis)\s*(\d{1,2}):(\d{2})")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def find_time_range(text: str) -> tuple[str | None, str | None]:
    """Return ("HH:MM", "HH:MM"|None) for the first time (range) in text."""
    m = _TIME_RANGE.search(text)
    if m:
        return f"{int(m[1]):02d}:{m[2]}", f"{int(m[3]):02d}:{m[4]}"
    m = _TIME.search(text)
    if m and int(m[1]) < 24:
        return f"{int(m[1]):02d}:{m[2]}", None
    return None, None


def combine(day: date, time: str | None) -> str:
    return f"{day.isoformat()}T{time}" if time else day.isoformat()
