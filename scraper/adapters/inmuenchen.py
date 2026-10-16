"""IN München (city magazine) — event listings from its WordPress REST API.

/wp-json/wp/v2/in-event-listing?search=blues returns every listing that mentions
blues anywhere (~170, almost all upcoming; past listings drop out). Each has:
  _embedded.wp:term  event_genre names, e.g. "Blues", "Bluesrock", "Folk-Pop"
  content            "<strong>Freitag, 16.10.2026<br>19:30 Uhr – 23:00 Uhr</strong>"
                     or "Samstag, 24.10.2026 20:00 Uhr bis Sonntag, 25.10.2026 02:00 Uhr",
                     then "<p><strong>Venue</strong> / <strong>Room</strong>, Street 1, 80331 München<br>…"
Genres become tags, so `filter: blues_title` keeps listings whose title or genre
says blues and drops ones that only mention it in the description.
Listings saying "Aktuell keine Termine" (no dates) are skipped.

params.max_pages: pages of 100 listings to read (default 3).
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

from ..models import Event, clean_text, guess_type
from ..registry import adapter
from ._html import soup, text

PER_PAGE = 100
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*Uhr")


@adapter("inmuenchen")
def scrape(source, ctx):
    api = urljoin(source["url"], "/wp-json/wp/v2/in-event-listing")
    params = source.get("params", {})
    events = []
    for page in range(1, params.get("max_pages", 3) + 1):
        raw = ctx.http.text(api, {
            "search": params.get("search", "blues"),
            "per_page": PER_PAGE,
            "page": page,
            "_embed": "wp:term",
            "_fields": "id,link,title,content,excerpt,_links,_embedded",
        })
        items = json.loads(raw)
        events.extend(parse(items, source.get("default_type", "concert")))
        if len(items) < PER_PAGE:
            break
    return events


def parse(items: list[dict], default_type: str = "concert") -> list[Event]:
    events = []
    for item in items:
        page = soup(item["content"]["rendered"])
        when = page.find("strong")
        start, end = _when(when.get_text(" ") if when else "")
        if not start:
            continue
        title = clean_text(html.unescape(item["title"]["rendered"]))
        venue, address = _place(page.find("p"))
        events.append(Event(
            title=title,
            type=guess_type(title, default_type),
            start=start,
            end=end,
            url=item["link"],
            venue=venue,
            address=address,
            description=text(soup(item.get("excerpt", {}).get("rendered", ""))),
            tags=[t["name"] for group in item.get("_embedded", {}).get("wp:term", [])
                  for t in group if t["taxonomy"] == "event_genre"],
        ))
    return events


def _when(header: str) -> tuple[str | None, str | None]:
    """'Fr, 16.10.2026 19:30 Uhr – 23:00 Uhr' / '… 20:00 Uhr bis So, 25.10.2026 02:00 Uhr' -> ISO start, end."""
    days = [f"{y}-{m}-{d}" for d, m, y in _DATE.findall(header)]
    times = [f"{int(h):02d}:{mi}" for h, mi in _TIME.findall(header)]
    if not days:
        return None, None
    start = f"{days[0]}T{times[0]}" if times else days[0]
    end_day = days[1] if len(days) > 1 else days[0]
    end = f"{end_day}T{times[1]}" if len(times) > 1 else (end_day if len(days) > 1 else None)
    return start, end


def _place(par) -> tuple[str | None, str | None]:
    """'<strong>Muffatwerk</strong> / <strong>Muffathalle</strong>, Zellstr. 4, 81667 München<br>…'"""
    if par is None or not par.find("strong"):
        return None, None
    names = [text(s) for s in par.find_all("strong")]
    # "Deutsches Theater / Deutsches Theater Silbersaal" -> just the room
    venue = names[-1] if len(names) == 2 and names[1].startswith(names[0]) else " / ".join(names)
    line = []
    for node in par.children:
        if getattr(node, "name", None) == "br":
            break
        line.append(node.get_text(" ") if hasattr(node, "get_text") else str(node))
    rest = clean_text(" ".join(line)).split(",")[1:]
    address = ", ".join(p.strip() for p in rest if p.strip())
    return venue, address or None
