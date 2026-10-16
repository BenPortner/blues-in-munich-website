"""SwinginMunich.de — Drupal 7 swing calendar (Lindy Hop, Balboa, Shag, Boogie, Blues).

The site links an iCal feed, but it answers 403 to anonymous visitors, so this
reads the HTML calendar instead.

Listing: /de/kalender?page=N (Drupal pager, ~15 dates per page, an empty page
after the last one). Each item: div.eventstring > a[href="/de/node/<id>/<YYYYMMDD>"]
with a truncated "Title… · Venue" and div.eventtype "Social Dance / DJ".
Detail: the linked node page (a colorbox popup) has p.cbox_title, p.cbox_date
"Sonntag, 18. Oktober 2026 - 19:15", p.cbox_body, .cbox_location, .cbox_address,
.cbox_link a, .cbox_type. Recurring events share one node, so each node is
fetched once. robots.txt asks for Crawl-delay: 10.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from ..dates import combine, find_time_range
from ..models import Event, guess_type
from ..registry import adapter
from ._html import soup, text

_NODE = re.compile(r"/node/(\d+)/(\d{4})(\d{2})(\d{2})")
CRAWL_DELAY = 10


@adapter("swinginmunich")
def scrape(source, ctx):
    params = source.get("params", {})
    listing = urljoin(source["url"], "/de/kalender")
    delay = params.get("delay", CRAWL_DELAY)
    occurrences = []
    for page in range(params.get("max_pages", 6)):
        found = parse_listing(ctx.http.text(listing, {"page": page} if page else None, delay=delay), listing)
        if not found:
            break
        occurrences.extend(found)

    details = {}  # node id -> detail fields; one fetch per node
    events = []
    for node_url, day in occurrences:
        node = _NODE.search(node_url)[1]
        if node not in details:
            details[node] = parse_detail(ctx.http.text(node_url, delay=delay))
        if details[node]:
            events.append(_event(details[node], node_url, day, source.get("default_type", "social")))
    return events


def parse_listing(html, base_url) -> list[tuple[str, date]]:
    """(node page url, day) for every calendar entry on a listing page."""
    result = []
    for link in soup(html).select("div.eventstring a[href]"):
        m = _NODE.search(link["href"])
        if not m:
            continue
        path = urlparse(urljoin(base_url, link["href"]))._replace(query="").geturl()
        result.append((path, date(int(m[2]), int(m[3]), int(m[4]))))
    return result


def parse_detail(html) -> dict | None:
    page = soup(html)
    title = text(page.select_one(".cbox_title"))
    if not title:
        return None
    link = page.select_one(".cbox_link a[href]")
    return {
        "title": title,
        "when": text(page.select_one(".cbox_date")),
        "body": text(page.select_one(".cbox_body")),
        "venue": text(page.select_one(".cbox_location")) or None,
        "address": text(page.select_one(".cbox_address")) or None,
        "link": link["href"].strip() if link else None,
        "kind": text(page.select_one(".cbox_type")),
    }


KONGRESSBAR_EVENTS = "https://kongressbar.de/events-live-bands-djs/"


def _url_override(title):
    # The calendar links Bluesverschwörung to a Facebook group; the venue's own page is better.
    return KONGRESSBAR_EVENTS if title.lower().startswith("bluesverschwörung") else None


def _event(detail, node_url, day, default_type) -> Event:
    # The date comes from the node url (one per occurrence); the time from the detail page.
    t_start, t_end = find_time_range(detail["when"])
    tags = [detail["kind"]] if detail["kind"] else []
    return Event(
        title=detail["title"],
        type=guess_type(" ".join([detail["title"], *tags]), default_type),
        start=combine(day, t_start),
        end=combine(day, t_end) if t_end else None,
        url=_url_override(detail["title"]) or detail["link"] or node_url,
        venue=detail["venue"],
        address=detail["address"],
        description=detail["body"],
        tags=tags,
    )
