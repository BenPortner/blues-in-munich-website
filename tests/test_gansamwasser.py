from scraper.adapters import gansamwasser
from scraper.filters import keep

from .conftest import TODAY, fixture

BASE = "https://www.gansamwasser.de/"
PROG = BASE + "kulturprogramm/"
OCTOBER = PROG + "programm-oktober/"


def parse(name, url=OCTOBER):
    return gansamwasser.parse(fixture(name), url, TODAY)


def test_gansamwasser_subpages():
    assert gansamwasser.subpages(fixture("gaw_kulturprogramm.html"), PROG) == [
        OCTOBER, PROG + "herbstfest/", PROG + "kinderprogramm/", PROG + "open-stages/"]


def test_gansamwasser_month_page():
    events = parse("gaw_programm.html")
    assert [(e.title, e.start, e.end) for e in events] == [
        ("Herbstfest", "2026-10-17", None),  # teaser of the Herbstfest page; assemble dedupes it
        ("Familienprogramm: Reisebericht Amazonas (Brasilien)", "2026-10-18T12:00", "2026-10-18T13:00"),
        ("Parkoustics", "2026-10-18T14:00", "2026-10-18T16:00"),
        ("Triple Snap", "2026-10-24T14:00", "2026-10-24T15:30"),
        ("Wildnistag für Jung & Alt", "2026-10-25T12:00", "2026-10-25T18:00"),
        ("Kasperltheater", "2026-10-27T14:00", "2026-10-27T17:00"),
        ("Ten Apart", "2026-10-31T14:00", "2026-10-31T16:00"),
    ]
    band = events[2]
    assert (band.type, band.url, band.tags) == ("concert", OCTOBER, ["Livemusik"])
    assert band.description.startswith("Parkoustics macht Akustikmusik")
    assert band.address == gansamwasser.ADDRESS
    # no blues in October's programme
    assert [e for e in events if keep(e, "blues")] == []


def test_gansamwasser_one_day_special_dates_its_sections():
    events = parse("gaw_herbstfest.html", PROG + "herbstfest/")
    # the evening acts were called off ("wetterbedingt abgesagt") and are dropped
    assert [(e.title, e.start, e.end) for e in events] == [
        ("HERBSTFEST", "2026-10-17T13:00", "2026-10-17T19:30"),
        ("Kinderprogramm", "2026-10-17T14:00", "2026-10-17T17:00"),
        ("Adrenalines", "2026-10-17T14:00", "2026-10-17T16:00"),
    ]
    assert events[2].description.startswith("Die ADRENALINES")
    # "neuem Repertoire aus Blues-Rock-Soul"
    assert [e.title for e in events if keep(e, "blues")] == ["Adrenalines"]


def test_gansamwasser_series_page():
    events = parse("gaw_kinderprogramm.html", PROG + "kinderprogramm/")
    # the undated Kasperltheater and the "Winterzauber" heading are skipped
    assert [(e.title, e.start) for e in events] == [
        ("Kinderprogramm zum Herbstfest", "2026-10-17T13:00"),
        ("Familienprogramm: Reisebericht Amazonas (Brasilien)", "2026-10-18T12:00"),
        ("Wildnistag für Familien", "2026-10-25T12:00"),
        ("Kinderkonzert: Tim Mohr für´s Kinderohr", "2026-12-05T13:00"),
    ]


def test_gansamwasser_date_list():
    assert parse("gaw_open_stages.html") == []  # its only date was cancelled
    html = fixture("gaw_open_stages.html").replace("-&gt; wetterbedingt abgesagt", "")
    [event] = gansamwasser.parse(html, PROG + "open-stages/", TODAY)
    # the year comes from the "2026" button, not the next 8 October
    assert (event.title, event.start, event.end) == ("Open Stage mit Marco", "2026-10-08T18:00", "2026-10-08T20:00")


def test_gansamwasser_date_range_heading():
    [event] = parse("gaw_winterzauber.html", BASE + "winterzauber/")
    assert (event.title, event.start, event.end) == ("Winterzauber im Gans am Wasser", "2026-11-27", "2027-01-01")


def test_gansamwasser_scrape(make_ctx):
    ctx = make_ctx({
        PROG + "programm-": "gaw_programm.html",
        PROG + "herbstfest/": "gaw_herbstfest.html",
        PROG + "kinderprogramm/": "gaw_kinderprogramm.html",
        PROG + "open-stages/": "gaw_open_stages.html",
        PROG: "gaw_kulturprogramm.html",
        BASE + "winterzauber/": "gaw_winterzauber.html",
    })
    events = gansamwasser.scrape({"url": BASE}, ctx)
    assert len(events) == 7 + 3 + 4 + 0 + 1
    assert ctx.http.calls[-1][0] == BASE + "winterzauber/"
