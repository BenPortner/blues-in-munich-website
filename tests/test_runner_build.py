import json
from datetime import date

from bs4 import BeautifulSoup

from scraper.__main__ import ROOT, scrape_source
from scraper.assemble import assemble, load_archive, load_raw, load_sources
from scraper.models import Event, slug
from scraper.registry import ADAPTERS, SkipSource, adapter
from web.build import build, calendar_events, months_later, regional
from web.highlights import Highlights

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


def collect(sources, ctx, previous, archive=None):
    """Scrape into data/raw (here: tmp_path/raw), then build events.json's content from it."""
    raw_dir = ctx.root / "raw"
    for source in sources:
        if source.get("enabled", True):
            scrape_source(source, ctx, raw_dir, previous["events"])
    return assemble(sources, raw_dir, previous, ctx.today, archive)


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


def test_failed_source_keeps_its_last_scrape(make_ctx):
    ctx = make_ctx()
    ok = src("s", "_test_static", params={"events": [ev("Blues Night", "2026-11-01T20:00")]})
    collect([ok], ctx, {"events": []})
    result = collect([{**ok, "adapter": "_test_broken"}], ctx, {"events": []})
    assert [e["title"] for e in result["events"]] == ["Blues Night"]
    assert result["sources"][0]["status"] == "failed"
    raw = load_raw(ctx.root / "raw", "s")
    assert raw["status"]["status"] == "failed" and raw["events"][0]["title"] == "Blues Night"


def test_assemble_without_raw_file_uses_last_events_json(tmp_path):
    previous = {"events": [Event(title="Blues Night", type="concert", start="2026-11-01", source_id="s",
                                 source_name="S", id="abc").to_dict()],
                "sources": [{"id": "s", "name": "S", "status": "ok", "kept": 1}]}
    result = assemble([src("s", "_test_static")], tmp_path / "raw", previous, TODAY)
    assert [e["id"] for e in result["events"]] == ["abc"]
    assert result["sources"][0]["status"] == "ok"


def test_assemble_reapplies_filters_without_scraping(make_ctx):
    ctx = make_ctx()
    source = src("s", "_test_static", params={"events": [ev("Blues Jam", "2026-10-20T20:00"),
                                                         ev("Jazz Trio", "2026-10-20T21:00")]})
    collect([source], ctx, {"events": []})
    raw_dir = ctx.root / "raw"
    assert [e["title"] for e in assemble([source], raw_dir, {"events": []}, TODAY)["events"]] == ["Blues Jam"]
    loose = {**source, "adapter": "_test_broken", "filter": "none"}  # never scraped again
    assert len(assemble([loose], raw_dir, {"events": []}, TODAY)["events"]) == 2
    strict = {**source, "exclude": ["jam"]}
    assert assemble([strict], raw_dir, {"events": []}, TODAY)["events"] == []


def test_partial_scrape_leaves_other_raw_files(make_ctx):
    ctx = make_ctx()
    a = src("a", "_test_static", params={"events": [ev("Blues Jam", "2026-10-20T20:00")]})
    b = src("b", "_test_static", params={"events": [ev("Blues Night", "2026-10-21T20:00")]})
    collect([a, b], ctx, {"events": []})
    scrape_source({**b, "params": {"events": [ev("Blues Ball", "2026-10-22T20:00")]}}, ctx, ctx.root / "raw")
    result = assemble([a, b], ctx.root / "raw", {"events": []}, TODAY)
    assert [e["title"] for e in result["events"]] == ["Blues Jam", "Blues Ball"]


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


ARCHIVE = {"since": "2026-01-01", "types": ["class", "workshop"]}


def test_load_archive(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("archive:\n  since: 2026-01-01\nsources: []\n")
    assert load_archive(path) == {"since": "2026-01-01",
                                  "types": ["class", "workshop", "social", "concert"]}
    path.write_text("archive:\n  since: 2026-01-01\n  types: [class, workshop]\nsources: []\n")
    assert load_archive(path) == ARCHIVE
    path.write_text("sources: []\n")
    assert load_archive(path) is None


def test_archive_keeps_past_classes_and_workshops(make_ctx):
    source = src("s", "_test_static", params={"events": [
        ev("Blues course", "2026-09-23T18:45", type="class", dates=["2026-09-23", "2026-09-30"]),
        ev("Blues Workshop", "2026-07-11T12:00", type="workshop"),
        ev("Blues Gig", "2026-07-11T20:00"),                          # past concert
        ev("Old Blues Workshop", "2025-12-06T12:00", type="workshop"),  # before `since`
        ev("Blues Night", "2026-10-20T20:00"),
    ]})
    result = collect([source], make_ctx(), {"events": []}, ARCHIVE)
    assert [e["title"] for e in result["events"]] == ["Blues Workshop", "Blues course", "Blues Night"]
    assert result["sources"][0]["kept"] == 3
    without = collect([source], make_ctx(), {"events": []})
    assert [e["title"] for e in without["events"]] == ["Blues Night"]


def test_archive_carries_over_past_events_from_last_run(make_ctx):
    def old(title, start, source_id="s", **kw):
        return Event(title=title, type=kw.pop("type", "workshop"), start=start, source_id=source_id,
                     source_name=source_id, id=title, **kw).to_dict()
    previous = {"events": [
        old("Blues Workshop März", "2026-03-07T16:00"),                 # gone from the site
        old("Blues Workshop", "2026-07-11T12:00"),                      # still on the site
        old("Blues Gig", "2026-07-11T20:00", type="concert"),           # past concert
        old("Other Workshop", "2026-05-16T16:00", source_id="other"),   # source didn't run
    ]}
    source = src("s", "_test_static", params={"events": [
        ev("Blues Workshop", "2026-07-11T12:00", type="workshop"), ev("Blues Night", "2026-10-20T20:00")]})
    result = collect([source], make_ctx(), previous, ARCHIVE)
    assert [e["title"] for e in result["events"]] == ["Blues Workshop März", "Blues Workshop", "Blues Night"]
    assert result["events"][1]["id"] != "Blues Workshop"  # the fresh copy wins over last run's


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
    subscribe = page.select_one("#subscribe")
    assert subscribe["href"] == "webcal://www.bluesinmunich.de/events.ics"
    assert subscribe["data-android-href"] == (
        "https://calendar.google.com/calendar/render?cid=webcal%3A%2F%2Fwww.bluesinmunich.de%2Fevents.ics")
    assert (out / "static" / "style.css").exists()
    ics = (out / "events.ics").read_text()
    assert ics.count("BEGIN:VEVENT") == 3  # two class sessions + one concert
    assert "DTSTART;TZID=Europe/Berlin:20261028T184500" in ics
    cal = json.loads(page.select_one("#calendar-data").string)
    assert [(c["title"], c["start"]) for c in cal] == [
        ("Blues · alle Level", "2026-10-21T18:45"), ("Blues · alle Level", "2026-10-28T18:45"),
        ("Louis Ville", "2026-10-21T20:30")]


def test_build_site_past_section(tmp_path):
    def school_event(title, start, type_, **kw):
        return Event(title=title, type=type_, start=start, url="https://s.example/", source_id="s",
                     source_name="School", school_name="School", school_url="https://s.example/",
                     id=slug(title), **kw).to_dict()
    data = {
        "generated_at": "2026-10-16T04:00:00+00:00",
        "sources": [],
        "events": [
            school_event("Blues course", "2026-09-23T18:45", "class", end="2026-09-23T19:45",
                         recurrence="Wednesdays 18:45–19:45", dates=["2026-09-23", "2026-09-30"]),
            school_event("Blues Workshop März", "2026-03-07T16:00", "workshop"),
            school_event("Blues Social", "2026-10-21T20:00", "social"),
        ],
    }
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY)

    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert [c.h4.get_text() for c in page.select("#upcoming .card")] == ["Blues Social"]
    assert [c.h4.get_text() for c in page.select("#past .card")] == ["Blues course", "Blues Workshop März"]
    assert [h.get_text() for h in page.select("#past .month h2")] == ["September 2026", "March 2026"]
    assert "Sessions: 23 Sep, 30 Sep" in page.select_one("#past .card").get_text()
    assert page.select_one("#past summary span").get_text() == "2"
    # chips count upcoming events, but past-only types still get one
    chips = {b["data-filter"]: b.span.get_text() for b in page.select(".chip[data-filter]")}
    assert chips == {"all": "1", "class": "0", "workshop": "0", "social": "1"}
    cal = json.loads(page.select_one("#calendar-data").string)
    assert [c["start"] for c in cal] == ["2026-03-07T16:00", "2026-09-23T18:45", "2026-09-30T18:45",
                                         "2026-10-21T20:00"]


def test_calendar_events():
    course = Event(title="Course", type="class", start="2026-10-21T18:45", end="2026-10-21T19:45",
                   dates=["2026-10-21", "2026-10-28"], id="c")
    fest = Event(title="Fest", type="workshop", start="2026-10-24", end="2026-10-25", id="f")
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


def test_region_switch(tmp_path):
    gig = lambda title, address, type="concert": Event(title=title, type=type, start="2026-10-21T20:00",
                                                       address=address, id=slug(title)).to_dict()
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        gig("City gig", "Blumenstraße 7, 80331 München"),
        gig("Village gig", "Obermühle 1, 82392 Habach"),
        gig("Garching gig", "Bürgerplatz 9, 85748 Garching bei München"),  # "München" in the name
        gig("No postcode", "Westpark"),                                     # counts as Munich
        gig("Augsburg class", "Viktoriastraße 3b, 86150 Augsburg", type="class"),  # any type
    ]}
    assert [regional(Event.from_dict(e)) for e in data["events"]] == [False, True, True, False, True]
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    picks = tmp_path / "highlights.yaml"
    picks.write_text("events: [City gig, Village gig]", encoding="utf-8")
    build(data_path, tmp_path / "dist", TODAY, Highlights.load(picks))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert [c.h4.get_text() for c in page.select(".card[data-regional]")] == [
        "Augsburg class", "Garching gig", "Village gig"]
    # the place menu offers Munich (2 upcoming events) and Munich and region (5)
    assert [b.get_text(" ", strip=True) for b in page.select(".place-menu [data-area]")] == [
        "Munich 2", "Munich and region 5"]
    # chips count without and with the region; without JS the page lists everything
    counts = {b["data-filter"]: (b["data-counts"], b.span.get_text()) for b in page.select(".chip[data-filter]")}
    assert counts == {"all": ("2 5", "5"), "highlight": ("1 2", "2"), "class": ("0 1", "1"), "concert": ("2 4", "4")}
    # an out-of-town highlight is a highlight like any other, marked so the page can leave it out
    assert [li.a.get_text() for li in page.select("#spotlight li[data-regional]")] == ["Village gig"]
    cal = {c["title"]: c["extendedProps"] for c in json.loads(page.select_one("#calendar-data").string)}
    assert cal["Village gig"]["regional"] is True and "regional" not in cal["City gig"]

    # no switch when every concert is in town
    data["events"] = data["events"][:1]
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY, Highlights.load(picks))
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert page.select_one(".place") is None


def test_course_blocks_far_ahead_wait(tmp_path):
    def course(title, *dates, type_="class"):
        return Event(title=title, type=type_, start=f"{dates[0]}T19:35", end=f"{dates[0]}T20:35",
                     recurrence="Tuesdays 19:35–20:35" if type_ == "class" else None,
                     dates=list(dates) if type_ == "class" else [], id=slug(title)).to_dict()
    data = {"generated_at": "2026-10-16T04:00:00+00:00", "sources": [], "events": [
        course("This term", "2026-10-20", "2026-10-27"),
        course("Next term", "2026-12-01", "2026-12-08"),      # starts before 16 Dec: listed
        course("Winter term", "2027-01-12", "2027-01-19"),    # more than 2 months out: not yet
        course("Winter workshop", "2027-01-16", type_="workshop"),  # only course blocks wait
    ]}
    data_path = tmp_path / "events.json"
    data_path.write_text(json.dumps(data))
    build(data_path, tmp_path / "dist", TODAY)
    page = BeautifulSoup((tmp_path / "dist" / "index.html").read_text(encoding="utf-8"), "lxml")
    assert [c.h4.get_text() for c in page.select(".card")] == ["This term", "Next term", "Winter workshop"]
    assert {c["title"] for c in json.loads(page.select_one("#calendar-data").string)} == {
        "This term", "Next term", "Winter workshop"}
    assert "Winter term" not in (tmp_path / "dist" / "events.ics").read_text(encoding="utf-8")


def test_months_later():
    assert months_later(date(2026, 10, 16), 3) == date(2027, 1, 16)
    assert months_later(date(2026, 11, 30), 3) == date(2027, 2, 28)  # no 30 Feb
    assert months_later(date(2026, 1, 31), 1) == date(2026, 2, 28)
