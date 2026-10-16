from scraper.adapters import misterbs
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://mister-bs.bar/"


def test_misterbs_programme():
    events = misterbs.parse(fixture("mb_programm.html"), URL, TODAY)
    assert len(events) == 11  # 12 nights listed, one "Geschlossene Veranstaltung"
    assert not any("Geschlossen" in e.title for e in events)
    first = events[0]
    assert (first.title, first.start, first.type) == ("Elias Prinz & Giangiacomo Rosso", "2026-10-08T20:00", "concert")
    assert first.url == "https://mister-bs.bar/#programm"
    assert first.venue == "Mister B's" and "80336" in first.address
    assert first.description.startswith("Einmal im Monat ist Elias Prinz")
    last = events[-1]
    assert (last.title, last.start) == ("T. Bellevue Trio", "2026-10-31T20:00")
    assert "GALLERY" not in last.description  # stops at the end of the programme section
    # October has no blues acts
    assert [e for e in events if keep(e, "blues")] == []


def test_misterbs_blues_gig_passes_title_filter():
    html = """<div data-name="programm">
      <h1>Unser Live Programm im November</h1>
      <h2>Freitag 06. November | Hokie Joint Blues Band | ab 20:30 Uhr</h2>
      <p>Chicago Blues und Boogie.</p>
      <h2>Samstag 07. November ¦ Lisa Trio ¦ ab 20:00 Uhr</h2>
      <p>Jazz mit einem Hauch Blues.</p>
    </div>"""
    events = misterbs.parse(html, URL, TODAY)
    assert [(e.title, e.start) for e in events] == [
        ("Hokie Joint Blues Band", "2026-11-06T20:30"), ("Lisa Trio", "2026-11-07T20:00")]
    assert [e.title for e in events if keep(e, "blues_title")] == ["Hokie Joint Blues Band"]


def test_misterbs_scrape(make_ctx):
    ctx = make_ctx({URL: "mb_programm.html"})
    events = misterbs.scrape({"id": "misterbs", "url": URL}, ctx)
    assert len(events) == 11
    assert ctx.http.calls == [(URL, None)]
