"""Bürgerhaus Glockenbachwerkstatt — WordPress theme listing.

Listing: /veranstaltungen/?date=&category=<slug> (e.g. "fishnblues" = the
weekly Fish'n Blues concerts). Each item:
  div.events > div.event: a.eventlink, span.eventtime "20:30 Uhr",
  span.imgdate "21.10." (no year), h2.event__title, .event__location (category links)
"""
from __future__ import annotations

from urllib.parse import urljoin

from ..dates import combine, find_dates, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text

ADDRESS = "Blumenstraße 7, 80331 München"


@adapter("glockenbachwerkstatt")
def scrape(source, ctx):
    params = source.get("params", {})
    listing = urljoin(source["url"], "/veranstaltungen/")
    events = []
    for category in params.get("categories", [""]):
        html = ctx.http.text(listing, {"date": "", "category": category})
        events.extend(parse(html, listing, ctx.today))
    return events


def parse(html, base_url, today=None):
    events = []
    for node in soup(html).select("div.events > div.event"):
        title_el = node.select_one(".event__title")
        date_el = node.select_one(".imgdate")
        if not title_el or not date_el:
            continue
        days = find_dates(text(date_el), today=today)
        if not days:
            continue
        link = title_el.find("a") or node.select_one("a.eventlink")
        times = node.select(".eventtime")
        t_start, t_end = find_time_range(text(times[0]) if times else "")
        location = node.select_one(".event__location")
        categories = [text(a) for a in location.find_all("a")] if location else []
        extra = text(location)
        for category in categories:
            extra = extra.replace(category, "", 1)
        price = text(node.select_one(".eventtime.price"))
        description = " · ".join(p for p in [extra.strip(), price] if p)
        title = text(title_el)
        events.append(Event(
            title=title,
            type="concert" if "Konzert" in categories else guess_type(" ".join([title, *categories]), "concert"),
            start=combine(days[0], t_start),
            end=combine(days[0], t_end) if t_end else None,
            url=urljoin(base_url, link["href"]) if link else base_url,
            venue="Glockenbachwerkstatt",
            address=ADDRESS,
            description=description,
            tags=categories,
        ))
    return events
