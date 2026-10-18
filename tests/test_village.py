from scraper.adapters import village
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://www.village-habach.de/"
LISTING = "https://www.village-habach.de/programm/"


def test_village_programme():
    events = village.parse(fixture("village_programm.html"), LISTING, TODAY)
    assert len(events) == 50  # 56 nights listed: 3 called off, 3 moved (listed again on the new date)
    titles = [e.title for e in events]
    assert not any("+" in t or "Danny Bryant" in t for t in titles)
    first = events[0]
    assert (first.title, first.start, first.type) == ("Ben Poole (GBR)", "2026-10-18T20:15", "concert")
    assert first.url == "https://village-habach.de/programm/?single=a0bb1c36d2d69f5fc700d565dd7853c8"
    assert first.venue == "Village Habach" and "82392 Habach" in first.address
    assert first.description.startswith("Mischung aus Blues, Rock und Soul")
    assert "weiterlesen" not in first.description
    # "+++ZUSATZKONZERT+++ Aynsley Lister (GBR)": the note goes, the gig stays
    assert (events[3].title, events[3].start) == ("Aynsley Lister (GBR)", "2026-10-31T20:15")
    # a gig moved to 23.01. shows up once, on its new date
    assert [e.start for e in events if e.title == "UNDER ATTIC"] == ["2027-01-23T20:15"]
    # the years roll over with the list: January is 2027, and so is the last October
    assert next(e for e in events if e.title == "BLUES CARAVAN").start == "2027-01-22T20:15"
    assert (events[-1].title, events[-1].start) == ("Village Session und gemütliches Treffen für Alle", "2027-10-07")


def test_village_blues_filter():
    events = village.parse(fixture("village_programm.html"), LISTING, TODAY)
    kept = [e.title for e in events if keep(e, "blues")]
    assert "Ben Poole (GBR)" in kept and "Kai Strauss & The Electric Blues Allstars (GER/USA/UK)" in kept
    assert "Jamaram" not in kept and "Thunderbirds" not in kept


def test_village_scrape(make_ctx):
    ctx = make_ctx({LISTING: "village_programm.html"})
    events = village.scrape({"id": "village-habach", "url": URL}, ctx)
    assert len(events) == 50
    assert ctx.http.calls == [(LISTING, None)]
