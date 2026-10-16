import json

from bs4 import BeautifulSoup

from scraper.__main__ import ROOT
from scraper.models import Event
from web.build import build, calendar_events
from web.highlights import Highlights

from .conftest import TODAY

HIGHLIGHTS_YAML = """
always:
  - source: bb
    types: [workshop]
min_capacity: 400
venues:
  - name: Schlachthof
    capacity: 500
  - name: Schlachthof Ox
    capacity: 50
  - name: Muffathalle
    capacity: 1400
  - name: Stadtsaal Fürstenfeld
    match: [Fürstenfeld Stadtsaal]
    capacity: 650
  - name: Strom
    capacity: 500
"""


def highlights(tmp_path) -> Highlights:
    path = tmp_path / "highlights.yaml"
    path.write_text(HIGHLIGHTS_YAML, encoding="utf-8")
    return Highlights.load(path)


def ev(title="Gig", **kw):
    return Event(title=title, type=kw.pop("type", "concert"), start=kw.pop("start", "2026-10-21"), **kw)


def test_capacity_matching(tmp_path):
    h = highlights(tmp_path)
    assert h.capacity("Schlachthof – Saal") == 500
    assert h.capacity("Schlachthof – Ox") == 50                      # longest match wins
    assert h.capacity("Muffatwerk / Muffathalle") == 1400
    assert h.capacity("Veranstaltungsforum Fürstenfeld – Stadtsaal") == 650  # alias, accents ignored
    assert h.capacity("Stromberg Hall") is None                      # whole words only
    assert h.capacity("Unknown Bar") is None
    assert h.capacity(None) is None


def test_reason_big_venue(tmp_path):
    h = highlights(tmp_path)
    assert h.reason(ev(venue="Muffathalle")) == "Big venue: about 1,400 people"
    assert h.reason(ev(type="festival", venue="Strom")) == "Big venue: about 500 people"
    assert h.reason(ev(venue="Schlachthof Ox")) is None
    assert h.reason(ev(type="class", venue="Muffathalle")) is None
    assert h.reason(ev()) is None


def test_reason_always(tmp_path):
    h = highlights(tmp_path)
    workshop = ev("Blues Intensive", type="workshop", venue="Small Studio", source_id="bb", source_name="Boogie-Bären")
    assert h.reason(workshop) == "Workshop by Boogie-Bären"
    assert h.reason(ev(type="class", source_id="bb", source_name="Boogie-Bären")) is None
    assert h.reason(ev(type="workshop", source_id="other", source_name="Other School")) is None


def test_unknown_venues(tmp_path):
    events = [ev("A", venue="Strom"), ev("B", venue="Some Bar"), ev("C", venue="Some Bar"),
              ev("D", type="class", venue="Dance School")]
    assert highlights(tmp_path).unknown_venues(events) == ["Some Bar"]


def test_repo_highlights_yaml():
    h = Highlights.load(ROOT / "highlights.yaml")
    assert h.capacity("Muffatwerk / Muffathalle") >= h.min_capacity
    assert h.capacity("Glockenbachwerkstatt") < h.min_capacity
    # Boogie-Bären workshops are always highlights
    workshop = ev(type="workshop", source_id="boogie-baeren", source_name="Boogie-Bären München")
    assert h.reason(workshop)


def test_build_marks_highlights(tmp_path):
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        ev("Big Show", start="2026-10-21T20:00", venue="Muffatwerk / Muffathalle", id="big").to_dict(),
        ev("Blues Intensive", type="workshop", start="2026-10-22", source_id="bb", source_name="Boogie-Bären",
           id="ws").to_dict(),
        ev("Bar Gig", start="2026-10-23T20:00", venue="Some Bar", id="bar").to_dict(),
    ]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    unknown = build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
    assert unknown == ["Some Bar"]

    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    cards = page.select(".card")
    assert [c.has_attr("data-highlight") for c in cards] == [True, True, False]
    assert cards[0].select_one(".star").text == "★ Highlight"
    assert not cards[0].select_one(".star").has_attr("title")  # the reason stays out of the page
    assert page.select_one('.chip[data-filter="highlight"] span').text == "2"
    cal = {c["id"]: c for c in json.loads(page.select_one("#calendar-data").string)}
    assert cal["big-0"]["extendedProps"]["highlight"] is True
    assert cal["ws-0"]["extendedProps"]["highlight"] is True
    assert "highlight" not in cal["bar-0"]["extendedProps"]


def test_no_highlight_chip_without_highlights(tmp_path):
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        ev("Bar Gig", start="2026-10-22T20:00", venue="Some Bar", id="bar").to_dict()]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert page.select_one('.chip[data-filter="highlight"]') is None
    assert "highlight" not in calendar_events([Event.from_dict(data["events"][0])])[0]["extendedProps"]


def test_past_highlight_keeps_chip(tmp_path):
    # Only an archived Boogie-Bären workshop: the chip stays (counting 0 upcoming), the card keeps its badge
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        ev("Blues Intensive", type="workshop", start="2026-10-10", source_id="bb", source_name="Boogie-Bären",
           id="ws").to_dict()]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert page.select_one('.chip[data-filter="highlight"] span').text == "0"
    assert page.select_one("#past .card")["data-highlight"] == ""


def test_spotlight_months():
    from datetime import date
    from web.build import spotlight_months
    assert spotlight_months(date(2026, 10, 17)) == (date(2026, 10, 1), date(2026, 11, 1))
    assert spotlight_months(date(2026, 12, 31)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert spotlight_months(date(2027, 1, 31)) == (date(2027, 1, 1), date(2027, 2, 1))


def test_spotlight_lists_this_and_next_months_highlights(tmp_path):
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        ev("Big Show", start="2026-10-21T20:00", venue="Muffathalle", id="oct").to_dict(),
        ev("Blues Intensive", type="workshop", start="2026-11-28", source_id="bb", source_name="Boogie-Bären",
           id="nov").to_dict(),
        ev("Later Show", start="2026-12-01T20:00", venue="Muffathalle", id="dec").to_dict(),
        ev("Bar Gig", start="2026-10-23T20:00", venue="Some Bar", id="bar").to_dict(),
    ]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    box = page.select_one("#spotlight")
    assert "October & November" in box.h2.text
    items = box.select("li")
    assert [li.a.text for li in items] == ["Big Show", "Blues Intensive"]
    assert items[0].time.text.strip() == "Wed 21 Oct · 20:00"
    assert items[1].select_one(".where") is None and "Boogie" not in box.text  # no reason shown
    assert len(page.select("#upcoming .card")) == 4  # the full list is unchanged


def test_no_spotlight_without_upcoming_highlights(tmp_path):
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        ev("Later Show", start="2026-12-01T20:00", venue="Muffathalle", id="dec").to_dict()]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert page.select_one("#spotlight") is None


def test_reason_known_artist(tmp_path):
    h = highlights(tmp_path)
    assert h.reason(ev(venue="Some Bar", known_artist="Eric Bibb")) == "Well-known artist: Eric Bibb"
    assert h.reason(ev(type="workshop", known_artist="Eric Bibb")) is None


def test_lastfm_credit_only_with_artist_data(tmp_path):
    def page_for(events):
        data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": events}
        data_path = tmp_path / "events.json"
        data_path.write_text(json.dumps(data))
        build(data_path, tmp_path / "dist", TODAY, highlights(tmp_path))
        return BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")

    plain = page_for([ev("Bar Gig", start="2026-10-22T20:00", venue="Some Bar", id="bar").to_dict()])
    assert plain.select_one(".lastfm") is None
    famous = page_for([ev("Eric Bibb", start="2026-10-22T20:00", venue="Some Bar", known_artist="Eric Bibb",
                          id="bibb").to_dict()])
    credit = famous.select_one(".lastfm a")
    assert credit.text == "powered by AudioScrobbler" and credit["href"] == "https://www.last.fm/"
    assert famous.select_one(".card")["data-highlight"] == ""
    assert "Eric Bibb" in famous.select_one("#spotlight").text
