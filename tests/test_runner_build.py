import json
from datetime import date

from bs4 import BeautifulSoup

from scraper.__main__ import collect, load_sources, ROOT
from scraper.models import Event
from scraper.registry import ADAPTERS, SkipSource, adapter
from web.build import build, calendar_events

from .conftest import TODAY


def src(id_, adapter_name, **extra):
    return {"id": id_, "name": id_.title(), "kind": "venue", "url": f"https://{id_}.example/",
            "adapter": adapter_name, "filter": "blues", **extra}


@adapter("_test_static")
def _static(source, ctx):
    return [Event.from_dict(e) for e in source["params"]["events"]]


@adapter("_test_api", allow_empty=True)
def _api(source, ctx):
    return []


@adapter("_test_broken")
def _broken(source, ctx):
    raise ConnectionError("site down")


@adapter("_test_skip")
def _skip(source, ctx):
    raise SkipSource("no key")


def ev(title, start, **kw):
    return {"title": title, "type": kw.pop("type", "concert"), "start": start, **kw}


def test_sources_yaml_is_valid():
    sources = load_sources(ROOT / "sources.yaml")
    from scraper.registry import get_adapter
    for s in sources:
        assert get_adapter(s["adapter"])
        assert s["kind"] in {"school", "venue", "band", "aggregator", "manual"}
        assert s.get("filter", "blues") in {"blues", "blues_title", "none"}


def test_filters_dedupes_and_drops_past(make_ctx):
    sources = [
        src("a", "_test_static", params={"events": [
            ev("Blues Jam", "2026-10-20T20:00"),
            ev("Jazz Trio", "2026-10-20T20:00"),          # not blues
            ev("Old Blues Gig", "2026-10-01T20:00"),       # past
        ]}),
        src("b", "_test_static", params={"events": [ev("Blues  jam", "2026-10-20T21:00")]}),  # dup of a
    ]
    result = collect(sources, make_ctx(), {"events": []})
    assert [e["title"] for e in result["events"]] == ["Blues Jam"]
    assert [s["kept"] for s in result["sources"]] == [1, 0]


def test_failed_source_reuses_previous_events(make_ctx):
    previous = {"events": [Event(title="Blues Night", type="concert", start="2026-11-01",
                                 source_id="down", source_name="Down", id="abc").to_dict()]}
    result = collect([src("down", "_test_broken")], make_ctx(), previous)
    assert [e["title"] for e in result["events"]] == ["Blues Night"]
    assert result["sources"][0]["status"] == "failed"
    assert "site down" in result["sources"][0]["error"]


def test_empty_adapter_counts_as_failure(make_ctx):
    result = collect([src("empty", "_test_static", params={"events": []})], make_ctx(), {"events": []})
    assert result["sources"][0]["status"] == "failed"


def test_empty_api_result_counts_as_ok(make_ctx):
    result = collect([src("api", "_test_api")], make_ctx(), {"events": []})
    assert result["sources"][0]["status"] == "ok"
    assert result["sources"][0]["found"] == 0


def test_skipped_source(make_ctx):
    result = collect([src("tm", "_test_skip")], make_ctx(), {"events": []})
    assert result["sources"][0]["status"] == "skipped"


def test_school_link_and_band_prefix(make_ctx):
    school = src("school", "_test_static", kind="school",
                 params={"events": [ev("Blues 1", "2026-10-21T18:45", type="class", dates=["2026-10-21", "2026-10-28"])]})
    band = src("band", "_test_static", kind="band", filter="none",
               params={"events": [ev("Live-Konzert", "2026-12-04T17:30")]})
    result = collect([school, band], make_ctx(), {"events": []})
    by_source = {e["source_id"]: e for e in result["events"]}
    assert by_source["school"]["school_url"] == "https://school.example/"
    assert by_source["school"]["school_name"] == "School"
    assert by_source["band"]["school_url"] is None
    assert by_source["band"]["title"] == "Band: Live-Konzert"


def test_class_with_upcoming_sessions_is_kept(make_ctx):
    course = ev("Blues course", "2026-10-07T18:45", type="class",
                dates=["2026-10-07", "2026-10-14", "2026-10-21"])
    result = collect([src("s", "_test_static", params={"events": [course]})], make_ctx(), {"events": []})
    assert len(result["events"]) == 1


def test_build_site(tmp_path):
    data = {
        "generated_at": "2026-10-16T04:00:00+00:00",
        "sources": [{"id": "vc", "name": "Vintage Club", "url": "https://www.vintage-club.de/",
                     "kind": "school", "status": "ok", "kept": 1}],
        "events": [
            Event(title="Blues · alle Level", type="class", start="2026-10-21T18:45", end="2026-10-21T19:45",
                  url="https://www.vintage-club.de/classes.aspx", venue="Vintage Club",
                  recurrence="Wednesdays 18:45–19:45", dates=["2026-10-21", "2026-10-28"],
                  source_id="vc", source_name="Vintage Club", school_name="Vintage Club",
                  school_url="https://www.vintage-club.de/", id="c1").to_dict(),
            Event(title="Louis Ville", type="concert", start="2026-10-21T20:30",
                  url="https://www.glockenbachwerkstatt.de/events/x/", source_id="g",
                  source_name="Glockenbachwerkstatt", id="c2").to_dict(),
        ],
    }
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    out = tmp_path / "dist"
    build(data_path, out, TODAY)

    page = BeautifulSoup((out / "index.html").read_text(encoding="utf-8"), "lxml")
    cards = page.select(".card")
    assert [c["data-type"] for c in cards] == ["class", "concert"]
    assert page.select_one(".card .school")["href"] == "https://www.vintage-club.de/"
    assert cards[1].h4.a["href"] == "https://www.glockenbachwerkstatt.de/events/x/"
    assert "Upcoming sessions: 21 Oct, 28 Oct" in cards[0].get_text()
    assert (out / "static" / "style.css").exists()
    ics = (out / "events.ics").read_text()
    assert ics.count("BEGIN:VEVENT") == 3  # two class sessions + one concert
    assert "DTSTART;TZID=Europe/Berlin:20261028T184500" in ics
    cal = json.loads(page.select_one("#calendar-data").string)
    assert [(c["title"], c["start"]) for c in cal] == [
        ("Blues · alle Level", "2026-10-21T18:45"), ("Blues · alle Level", "2026-10-28T18:45"),
        ("Louis Ville", "2026-10-21T20:30")]


def test_calendar_events():
    course = Event(title="Course", type="class", start="2026-10-21T18:45", end="2026-10-21T19:45",
                   dates=["2026-10-21", "2026-10-28"], id="c")
    fest = Event(title="Fest", type="festival", start="2026-10-24", end="2026-10-25", id="f")
    night = Event(title="Night", type="concert", start="2026-10-24T20:00", end="2026-10-25T02:00", id="n")
    late = Event(title="Late", type="concert", start="2026-10-30T20:00", end="2026-10-31", id="l")
    cal = {c["id"]: c for c in calendar_events([course, fest, night, late])}
    assert (cal["c-1"]["start"], cal["c-1"]["end"]) == ("2026-10-28T18:45", "2026-10-28T19:45")
    assert (cal["f-0"]["end"], cal["f-0"]["allDay"]) == ("2026-10-26", True)  # exclusive end
    assert (cal["n-0"]["end"], cal["n-0"]["allDay"]) == ("2026-10-25T02:00", False)
    assert cal["l-0"]["end"] == "2026-11-01T00:00"  # mixed date/time stretches to end of day
    assert cal["c-0"]["extendedProps"] == {"type": "class", "label": "Class", "venue": None, "time": "18:45–19:45"}


def test_calendar_json_is_script_safe(tmp_path):
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        Event(title="</script><b>x", type="concert", start="2026-10-21", id="x").to_dict()]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY)
    html = (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")
    assert "</script><b>" not in html
    page = BeautifulSoup(html, "lxml")
    assert json.loads(page.select_one("#calendar-data").string)[0]["title"] == "</script><b>x"


def test_build_empty(tmp_path):
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps({"generated_at": "2026-10-16T04:00:00+00:00", "events": [], "sources": []}))
    build(data_path, tmp_path / "dist", date(2026, 10, 16))
    assert "No upcoming blues events" in (tmp_path / "dist" / "index.html").read_text()


def teardown_module():
    for name in ("_test_static", "_test_broken", "_test_skip"):
        ADAPTERS.pop(name, None)
