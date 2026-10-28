"""Truderinger Kulturkreis e.V. — Jimdo home page with the next few events.

The home page lists upcoming events as Jimdo modules (div.j-module) up to a heading
"Und das war schon...." (past events below it). Each event module starts with a red heading span like
"24.1.27 17h: HaberJazzBand", "So. 11.10.26 12Uhr "Motovidlo"" or "31.12.26 19h Silvesterkonzert",
followed by a short blurb. There are no event pages; most concerts are at the Kulturzentrum Trudering.
"""
from __future__ import annotations

import re

from ..dates import combine, find_dates
from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

VENUE = "Kulturzentrum Trudering"
ADDRESS = "Wasserburger Landstraße 32, 81825 München"
# "[So. ]24.1.27 17h: Title" / "11.10.26 12Uhr Title" / "19h30"
HEADING = re.compile(r"^(?:\w{2}\.\s*)?(\d{1,2}\.\d{1,2}\.\d{2,4})\s+(\d{1,2})(?:[:.]?(\d{2}))?\s*(?:h|Uhr)(\d{2})?\s*:?\s*(.+)$")


@adapter("truderinger_kulturkreis")
def scrape(source, ctx):
    return parse(ctx.http.text(source["url"]), source["url"], ctx.today)


def parse(html, base_url, today=None):
    events = []
    for module in soup(html).select("div.j-module"):
        if "das war schon" in text(module):
            break
        heading, match = next(((span, m) for span in module.select('span[style*="font-size"]')
                               if (m := HEADING.match(text(span)))), (None, None))
        if not match:
            continue
        day_text, hour, minute, minute_after_h, title = match.groups()
        days = find_dates(day_text, today=today)
        if not days:
            continue
        title = clean_text(title).strip('"„“ ')
        heading.extract()
        events.append(Event(
            title=title,
            type=guess_type(title, "concert"),
            start=combine(days[0], f"{int(hour):02d}:{minute or minute_after_h or '00'}"),
            url=base_url,
            venue=VENUE,
            address=ADDRESS,
            description=text(module),
        ))
    return events
