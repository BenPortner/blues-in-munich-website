"""muenchen-online.de (Das gelbe Heft) — a venue's page listing its upcoming events.

For venues that publish their programme only in a newsletter or on social media (e.g. Jazzbar Vogler).
The venue page (/veranstaltungsorte/<name>-<id>/) shows the address and nine teasers per page
(a.teaserbox: category, headline and "Mi 28.10. und Do 29.10., jeweils 19.30 Uhr | Venue" or
"Di 10.11. bis Sa 14.11., jeweils 19.30 Uhr | Venue"); further pages are <url>/page/N/.
A run of nights becomes one event with every night in `dates`.

params.page_url: the venue page on muenchen-online.de (source url is the venue's own site).
params.max_pages: listing pages to read (default 4).
"""
from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urljoin

from ..dates import combine, find_dates
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

_TIME = re.compile(r"(?<!\d)(\d{1,2})[.:](\d{2})\s*(?:-\s*(\d{1,2})[.:](\d{2})\s*)?Uhr")


@adapter("muenchen_online")
def scrape(source, ctx):
    params = source.get("params", {})
    url = params.get("page_url", source["url"]).rstrip("/") + "/"
    events = []
    for page in range(1, params.get("max_pages", 4) + 1):
        html = ctx.http.text(url if page == 1 else f"{url}page/{page}/")
        found = parse(html, url, ctx.today)
        events.extend(found)
        if not found or 'class="next page-numbers"' not in html:
            break
    return events


def parse(html, base_url, today=None):
    page = soup(html)
    lines = [text(p, ", ") for p in page.select("section .content-area p")]
    venue = lines[0] if lines else None
    address = next((line for line in lines if re.search(r"\b8\d{4}\b", line)), None)
    events = []
    for box in page.select("a.teaserbox"):
        when = text(box.select_one(".mo_teaser_time_location"))
        when, _, place = when.rpartition(" | ")
        days = find_dates(when, today=today)
        if not days:
            continue
        if len(days) == 2 and re.search(r"\bbis\b", when):
            days = [days[0] + timedelta(n) for n in range((days[1] - days[0]).days + 1)]
        m = _TIME.search(when)
        start = f"{int(m[1]):02d}:{m[2]}" if m else None
        end = f"{int(m[3]):02d}:{m[4]}" if m and m[3] else None
        title = clean_text(text(box.select_one(".mo_teaser_headline")))
        rubrik = text(box.select_one(".mo-events_teaser_rubrik"))
        events.append(Event(
            title=title,
            type=guess_type(f"{title} {rubrik}", "concert"),
            start=combine(days[0], start),
            end=combine(days[0], end) if end else None,
            url=urljoin(base_url, box["href"]),
            venue=place or venue,
            address=address,
            dates=[d.isoformat() for d in days] if len(days) > 1 else [],
        ))
    return events
