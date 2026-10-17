"""Rheinpfalz Schwabing (pub with live music Thu-Sat, regular blues sessions) — WordPress.

/veranstaltungen/ lists every upcoming gig with the Very Simple Event List plugin:
  div.vsel-content > div.vsel-meta > h2.vsel-meta-title, div.vsel-meta-date span "Sa., 24. Oktober 2026",
  div.vsel-meta-time span "20:00" (private events: "20:00 – 20:00"), then div.vsel-text with the
  band blurb (usually names its genres). There are no detail pages, so events link to the listing.
"""
from __future__ import annotations

from ..dates import combine, find_dates, find_time_range
from ..models import Event
from ..registry import adapter
from ._html import soup, text

VENUE = "Rheinpfalz Schwabing"
ADDRESS = "Kurfürstenstraße 35, 80801 München"
# Closures, private parties and notices are listed like gigs
NOT_A_GIG = ("geschlossen", "trauern")


@adapter("rheinpfalz_schwabing")
def scrape(source, ctx):
    listing = source["url"]
    return parse(ctx.http.text(listing), listing, ctx.today)


def parse(html, base_url, today=None):
    events = []
    for node in soup(html).select("div.vsel-content"):
        title = text(node.select_one(".vsel-meta-title"))
        days = find_dates(text(node.select_one(".vsel-meta-date")), today=today)
        if not title or not days or any(word in title.lower() for word in NOT_A_GIG):
            continue
        t_start, t_end = find_time_range(text(node.select_one(".vsel-meta-time")))
        if t_end and t_end <= (t_start or ""):  # "20:00 – 20:00" means no end time
            t_end = None
        events.append(Event(
            title=title,
            type="concert",
            start=combine(days[0], t_start),
            end=combine(days[0], t_end) if t_end else None,
            url=base_url,
            venue=VENUE,
            address=ADDRESS,
            description=text(node.select_one(".vsel-text")),
        ))
    return events
