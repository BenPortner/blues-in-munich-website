from scraper.adapters import tollwood
from scraper.filters import keep

from .conftest import fixture

URL = "https://www.tollwood.de/"
CALENDAR = "https://www.tollwood.de/kalender-winter-2026/"
EVENTS = "https://www.tollwood.de/veranstaltungen/2026/"


def test_tollwood_calendar_link():
    # the home page also links last winter's calendar
    assert tollwood.calendar_url(fixture("tw_home.html"), URL) == CALENDAR


def test_tollwood_calendar():
    events = tollwood.parse_calendar(fixture("tw_kalender.html"), CALENDAR)
    # 64 Hexenkessel nights, each day listed twice (mobile and desktop); circus and kids' rows go
    assert len(events) == 64
    assert len({(e.url, e.start) for e in events}) == 64
    first = events[0]
    assert (first.title, first.start, first.end, first.type) == (
        "Edwin Kimmler", "2026-11-24T16:30", "2026-11-24T18:00", "concert")
    assert first.url == EVENTS + "edwin-kimmler/"
    assert (first.venue, first.address) == ("Tollwood – Hexenkessel", "Theresienwiese, 80336 München")
    muddy = next(e for e in events if e.title == "Muddy What?")
    assert (muddy.start, muddy.url) == ("2026-12-22T19:30", EVENTS + "muddy-what-3/")
    assert not any(e.title in ("Kreativzeit", "Artistic Pole") for e in events)


def test_tollwood_detail_genre():
    assert tollwood.parse_detail(fixture("tw_muddy_what.html")) == (["New Blues"], "New Blues")
    tags, blurb = tollwood.parse_detail(fixture("tw_croakers.html"))
    assert tags == ["Rockabilly"] and blurb.startswith("Rockabilly Chris Aron & The Croakers")


def test_tollwood_scrape(make_ctx):
    routes = {URL + "kalender": "tw_kalender.html",
              EVENTS + "muddy-what-3/": "tw_muddy_what.html",
              EVENTS + "boogiemens-friends/": "tw_boogiemens.html",
              EVENTS + "kozmic-blue/": "tw_kozmic_blue.html",
              EVENTS: "tw_croakers.html",  # every other act: billed as rockabilly
              URL: "tw_home.html"}
    ctx = make_ctx(routes)
    events = tollwood.scrape({"id": "tollwood", "url": URL}, ctx)
    assert len(events) == 64
    urls = [url for url, _ in ctx.http.calls]
    assert urls[:2] == [URL, CALENDAR] and len(urls) == 2 + 64  # each act's page once
    kept = [(e.title, e.start, e.tags) for e in events if keep(e, "blues_title")]
    assert kept == [
        ("Kozmic Blue", "2026-12-09T19:30", ["Kosmischer Blues & Rock"]),
        ("Boogiemen’s Friends", "2026-12-12T16:00", ["Boogie Woogie & Blues der 20er & 30er Jahre"]),
        ("Muddy What?", "2026-12-22T19:30", ["New Blues"])]
    # a rockabilly band whose blurb mentions rhythm & blues stays out
    croakers = next(e for e in events if e.title == "Chris Aron & The Croakers")
    assert "Blues" in croakers.description and not keep(croakers, "blues_title")


def test_tollwood_off_season(make_ctx):
    ctx = make_ctx({CALENDAR: "tw_home.html", URL: "tw_home.html"})  # a calendar without rows
    assert tollwood.scrape({"id": "tollwood", "url": URL}, ctx) == []
    assert tollwood.scrape.allow_empty
