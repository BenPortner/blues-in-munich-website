"""Jazzclub Unterfahrt — programm.php?month=MM&year=YYYY.

Each item is a div.b-events__row with .b-events__el-title, .b-events__el-text,
.b-events__el-tag (series, e.g. "Blues") and .b-events__el-date[data-ts]
(epoch milliseconds). Detail link: programm-detail.php?dateID=N.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text

ADDRESS = "Einsteinstraße 42, 81675 München"
# "MO•02•11•2026, 20••30" — the visible text is local time
_WHEN = re.compile(r"(\d{2})•(\d{2})•(\d{4}),\s*(\d{1,2})••(\d{2})")


@adapter("unterfahrt")
def scrape(source, ctx):
    params = source.get("params", {})
    listing = urljoin(source["url"], "programm.php")
    events = []
    year, month = ctx.today.year, ctx.today.month
    for _ in range(params.get("months", 4)):
        html = ctx.http.text(listing, {"month": f"{month:02d}", "year": str(year)})
        events.extend(parse(html, listing))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return events


def parse(html, base_url):
    events = []
    for row in soup(html).select("div.b-events__row"):
        title_el = row.select_one(".b-events__el-title")
        date_el = row.select_one(".b-events__el-date[data-ts]")
        if not title_el or not date_el:
            continue
        m = _WHEN.search(text(date_el))
        if m:
            start = datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4]), int(m[5]))
        else:  # data-ts holds local wall-clock time encoded as UTC
            start = datetime.fromtimestamp(int(date_el["data-ts"]) / 1000, timezone.utc)
        link = row.select_one('a[href*="programm-detail.php"]')
        tags = [t for t in (text(el) for el in row.select(".b-events__el-tag")) if t]
        tags = [part.strip() for tag in tags for part in tag.split("|") if part.strip()]
        title = text(title_el)
        sold_out = "ausverkauft" in text(date_el).lower()
        description = text(row.select_one(".b-events__el-text"))
        einstein = any("einstein" in t.lower() for t in tags)
        events.append(Event(
            title=title,
            type=guess_type(title, "concert") if "session" in title.lower() else "concert",
            start=start.strftime("%Y-%m-%dT%H:%M"),
            url=urljoin(base_url, link["href"].split("#")[0]) if link else base_url,
            venue="Einstein Kultur" if einstein else "Jazzclub Unterfahrt",
            address=ADDRESS,
            description=("Sold out. " if sold_out else "") + description,
            tags=tags,
        ))
    return events
