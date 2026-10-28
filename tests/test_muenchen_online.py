from scraper.adapters import muenchen_online as mo

from .conftest import TODAY, fixture

URL = "https://www.muenchen-online.de/veranstaltungsorte/jazzbar-vogler-2361/"


def test_muenchen_online_venue_page():
    events = mo.parse(fixture("muenchen_online_vogler.html"), URL, TODAY)
    assert len(events) == 9
    first = events[0]
    assert (first.title, first.start, first.dates) == (
        "Michael Stephenson meets The Alexander Claffy Trio", "2026-10-28T19:30", ["2026-10-28", "2026-10-29"])
    assert (first.venue, first.address) == ("Jazzbar Vogler", "Rumfordstr. 17, 80469 München")
    assert first.url == "https://www.muenchen-online.de/veranstaltung/michael-stephenson-meets-the-alexander-claffy-trio-468261"
    run = next(e for e in events if e.title == "Cosimo & The Hot Coals")  # "Di 10.11. bis Sa 14.11."
    assert run.dates == ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"]
    furlonger = next(e for e in events if e.title == "Sam Furlonger Quartet")  # "jeweils19.30 Uhr"
    assert furlonger.start == "2026-11-05T19:30"


def test_muenchen_online_scrape_follows_pages(make_ctx):
    ctx = make_ctx({URL + "page/2/": "muenchen_online_vogler_p2.html", URL: "muenchen_online_vogler.html"})
    events = mo.scrape({"id": "jazzbar-vogler", "url": "https://www.jazzbar-vogler.com/", "params": {"page_url": URL}}, ctx)
    assert len(events) == 16
    assert [url for url, _ in ctx.http.calls] == [URL, URL + "page/2/"]  # page 2 has no "next" link
    assert events[-1].start == "2027-02-18T19:30"


JAZZ = "https://www.muenchen-online.de/jazz/"
GALLI = "https://www.muenchen-online.de/veranstaltung/jazz-blues-482005"


def test_muenchen_online_category_fetches_blues_event_pages(make_ctx):
    ctx = make_ctx({GALLI: "muenchen_online_galli.html", JAZZ: "muenchen_online_jazz.html"})
    events = mo.scrape({"id": "muenchen-online-jazz", "url": JAZZ, "params": {"max_pages": 1}}, ctx)
    assert len(events) == 9
    galli = next(e for e in events if e.title == "Jazz & Blues")
    assert (galli.start, galli.venue) == ("2026-10-29T20:00", "Galli Theater")
    assert (galli.address, galli.description) == (
        "Türkenstr. 86/ Amalienpassage, 80799 München", "mit Tricia Leonard und John Brunton")
    assert [url for url, _ in ctx.http.calls] == [JAZZ, GALLI]  # only the blues-titled listing
    assert all(e.address is None for e in events if e is not galli)
