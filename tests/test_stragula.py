from scraper.adapters import stragula
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://stragula.de/"
LISTING = "https://stragula.de/events.html"


def test_stragula_events():
    events = stragula.parse(fixture("stragula_events.html"), LISTING, TODAY)
    titles = [e.title for e in events]
    assert not any("Geschlossene Gesellschaft" in t for t in titles)
    first = events[0]
    assert (first.title, first.start, first.type) == ("Poffer", "2026-10-24T20:00", "concert")
    assert first.url == LISTING + "#:~:text=Poffer" and first.venue == "Stragula" and "80339 München" in first.address
    assert first.description.startswith("Der Songwriter aus Niederbayern")
    assert first.description.endswith("Eintritt: Frei")
    assert "www.poffer.com" not in first.description
    jakarta = next(e for e in events if e.title == "Jakarta Blues Band")
    assert jakarta.start == "2027-01-16T20:00"
    assert jakarta.url == LISTING + "#:~:text=Jakarta%20Blues%20Band"
    anni = next(e for e in events if e.title.startswith("Anni"))
    assert anni.url.endswith("#:~:text=Anni%20und%20Hans%3A%20Blues%20%26%20Jazz")


def test_stragula_blues_filter():
    events = stragula.parse(fixture("stragula_events.html"), LISTING, TODAY)
    kept = [e.title for e in events if keep(e, "blues_title")]
    assert "Jakarta Blues Band" in kept and "Anni und Hans: Blues & Jazz" in kept
    assert "Second Unit" not in kept and "Poffer" not in kept


def test_stragula_scrape(make_ctx):
    ctx = make_ctx({LISTING: "stragula_events.html"})
    events = stragula.scrape({"id": "stragula", "url": URL}, ctx)
    assert events and ctx.http.calls == [(LISTING, None)]
