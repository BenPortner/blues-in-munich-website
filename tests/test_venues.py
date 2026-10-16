import json

from bs4 import BeautifulSoup

from scraper.__main__ import ROOT
from scraper.models import Event
from web.build import build, calendar_events
from web.venues import Venues

from .conftest import TODAY

VENUES_YAML = """
highlight_min_capacity: 400
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


def venues(tmp_path) -> Venues:
    path = tmp_path / "venues.yaml"
    path.write_text(VENUES_YAML, encoding="utf-8")
    return Venues.load(path)


def test_capacity_matching(tmp_path):
    v = venues(tmp_path)
    assert v.capacity("Schlachthof – Saal") == 500
    assert v.capacity("Schlachthof – Ox") == 50                      # longest match wins
    assert v.capacity("Muffatwerk / Muffathalle") == 1400
    assert v.capacity("Veranstaltungsforum Fürstenfeld – Stadtsaal") == 650  # alias, accents ignored
    assert v.capacity("Stromberg Hall") is None                      # whole words only
    assert v.capacity("Unknown Bar") is None
    assert v.capacity(None) is None


def test_is_highlight(tmp_path):
    v = venues(tmp_path)
    assert v.is_highlight(Event(title="Big", type="concert", start="2026-10-21", venue="Muffathalle"))
    assert not v.is_highlight(Event(title="Small", type="concert", start="2026-10-21", venue="Schlachthof Ox"))
    assert not v.is_highlight(Event(title="Class", type="class", start="2026-10-21", venue="Muffathalle"))
    assert not v.is_highlight(Event(title="Nowhere", type="concert", start="2026-10-21"))


def test_unknown_venues(tmp_path):
    events = [Event(title=t, type=ty, start="2026-10-21", venue=ve) for t, ty, ve in [
        ("A", "concert", "Strom"), ("B", "concert", "Some Bar"), ("C", "concert", "Some Bar"),
        ("D", "class", "Dance School")]]
    assert venues(tmp_path).unknown(events) == ["Some Bar"]


def test_repo_venues_yaml_loads():
    v = Venues.load(ROOT / "venues.yaml")
    assert v.min_capacity > 0
    assert v.capacity("Muffatwerk / Muffathalle") >= v.min_capacity
    assert v.capacity("Glockenbachwerkstatt") < v.min_capacity


def test_build_marks_highlights(tmp_path):
    venues(tmp_path)  # writes tmp_path/venues.yaml
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        Event(title="Big Show", type="concert", start="2026-10-21T20:00", venue="Muffatwerk / Muffathalle",
              id="big").to_dict(),
        Event(title="Bar Gig", type="concert", start="2026-10-22T20:00", venue="Some Bar", id="bar").to_dict(),
    ]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    unknown = build(data_path, tmp_path / "dist", TODAY, venues_path=tmp_path / "venues.yaml")
    assert unknown == ["Some Bar"]

    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    cards = page.select(".card")
    assert [c.has_attr("data-highlight") for c in cards] == [True, False]
    assert "about 1,400 people" in cards[0].select_one(".star")["title"]
    assert page.select_one('.chip[data-filter="highlight"] span').text == "1"
    cal = {c["id"]: c for c in json.loads(page.select_one("#calendar-data").string)}
    assert cal["big-0"]["extendedProps"]["highlight"] is True
    assert "highlight" not in cal["bar-0"]["extendedProps"]


def test_no_highlight_chip_without_highlights(tmp_path):
    venues(tmp_path)
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        Event(title="Bar Gig", type="concert", start="2026-10-22T20:00", venue="Some Bar", id="bar").to_dict()]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, venues_path=tmp_path / "venues.yaml")
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert page.select_one('.chip[data-filter="highlight"]') is None
    assert calendar_events([Event.from_dict(data["events"][0])])[0]["extendedProps"].get("highlight") is None
