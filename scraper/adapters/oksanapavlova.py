"""Oksana Pavlova (dance teacher, Lindy Hop / Blues / Solo Jazz) — WordPress news posts.

The site's Events Calendar (/events/?ical=1) is empty and the weekly Kursplan is
an image, so one-off workshops are only announced as posts. We read the latest
posts from the WordPress REST API: /wp-json/wp/v2/posts?_fields=...
  title    "Blues Workshop am 11.07.2026", "08.11.26 Lindy Hop – Taster ..."
  content  "Wann: 11. Juli, 12:00–15:00 Uhr Wo: Arnulfstr. 195, 1. OG Preis: ..."
The event date comes from the title, else the first date in the text (years
inferred relative to the publish date). Posts without a date on or after their
publish date (thank-yous, general news) are skipped.

params.per_page: how many recent posts to read (default 20).
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from urllib.parse import urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

# "Wo: Arnulfstr. 195, 1. OG" / "Adresse: ..." on its own line (one paragraph line each)
_ADDRESS = re.compile(r"^\s*(?:Wo|Adresse|Ort)\s*:\s*(.+?)\s*$", re.M)


@adapter("oksanapavlova")
def scrape(source, ctx):
    api = urljoin(source["url"], "/wp-json/wp/v2/posts")
    params = {"per_page": source.get("params", {}).get("per_page", 20), "_fields": "id,date,link,title,content"}
    return parse(ctx.http.text(api, params), source.get("default_type", "workshop"))


def parse(raw: str, default_type: str = "workshop"):
    events = []
    for post in json.loads(raw):
        title = clean_text(html.unescape(post["title"]["rendered"]))
        content = soup(post["content"]["rendered"])
        body = text(content)
        published = date.fromisoformat(post["date"][:10])
        days = [d for d in find_dates(title, today=published) or find_dates(body, today=published)
                if d >= published]
        if not days:
            continue
        t_start, t_end = find_time_range(title)
        if not t_start:
            t_start, t_end = find_time_range(body)
        address = _ADDRESS.search(content.get_text("\n"))
        events.append(Event(
            title=title,
            type=guess_type(title, default_type),
            start=combine(days[0], t_start),
            end=combine(days[0], t_end) if t_end else None,
            url=post["link"],
            address=address.group(1).strip(" ,") if address else None,
            description=body,
        ))
    return events
