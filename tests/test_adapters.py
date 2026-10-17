import json
from datetime import date

from scraper.adapters import (boogie_baeren, glockenbachwerkstatt, ical, inmuenchen, jsonld, mfgigcal,
                              rheinpfalz_schwabing, swinginmunich, ticketmaster, unterfahrt, vintage_club)
from scraper.filters import keep

from .conftest import TODAY, fixture

VC = "https://www.vintage-club.de/"


def blues(events, mode="blues"):
    return [e for e in events if keep(e, mode)]


# --- Vintage Club ------------------------------------------------------------

def test_vintage_club_timetable_finds_blues_courses():
    events = vintage_club.parse_timetable(fixture("vc_classes.html"), VC + "classes.aspx", TODAY)
    assert len(events) > 80  # the whole grid is parsed
    found = {e.title: e for e in blues(events)}
    assert set(found) == {"California Blues · alle Level", "Blues · alle Level"}

    course = found["Blues · alle Level"]
    assert course.type == "class"
    assert course.dates == ["2026-10-21", "2026-10-28", "2026-11-04", "2026-11-11"]
    assert course.start == "2026-10-21T18:45" and course.end == "2026-10-21T19:45"
    assert course.recurrence == "Wednesdays 18:45–19:45"
    assert course.venue == "Vintage Club (VC Studio 2)"
    assert course.description.startswith("Keine Vorkenntnisse")  # Blues Explorers text


def test_vintage_club_timetable_registration_marker():
    events = vintage_club.parse_timetable(fixture("vc_classes.html"), VC + "classes.aspx", TODAY)
    shag = next(e for e in events if e.title.startswith("Shag 1"))
    assert not shag.title.startswith("*")
    assert vintage_club.REGISTRATION_NOTE in shag.description


def test_vintage_club_event_blocks():
    events = vintage_club.parse_event_blocks(fixture("vc_workshops.html"), VC + "workshops.aspx", "workshop", TODAY)
    by_title = {e.title: e for e in events}
    git_up = next(e for t, e in by_title.items() if "GIT UP" in t)
    assert (git_up.start, git_up.end, git_up.type) == ("2026-10-18T13:00", "2026-10-18T14:30", "workshop")
    weekend = by_title["Workshop-Weekend mit Nicholas (USA) & Tere (ESP)"]
    assert (weekend.start[:10], weekend.end[:10], weekend.type) == ("2026-10-31", "2026-11-01", "workshop")
    # The dance-style glossary further down mentions blues; it must not leak into blocks
    assert blues(events) == []


def test_vintage_club_record_hop_rnb_is_filtered():
    events = vintage_club.parse_event_blocks(fixture("vc_parties.html"), VC + "parties.aspx", "social", TODAY)
    assert any("Record Hop" in e.title for e in events)
    assert blues(events) == []


def test_vintage_club_scrape_dedupes_repeated_specials(make_ctx):
    ctx = make_ctx({
        VC + "classes.aspx": "vc_classes.html",
        VC + "workshops.aspx": "vc_workshops.html",
        VC + "parties.aspx": "vc_parties.html",
        VC + "index.aspx": "vc_index.html",
    })
    events = vintage_club.scrape({"id": "vc", "url": VC}, ctx)
    keys = [(e.title, e.start[:10]) for e in events if e.type != "class"]
    assert len(keys) == len(set(keys))


# --- Boogie-Bären -------------------------------------------------------------

def test_boogie_baeren_calendar():
    events = boogie_baeren.parse(fixture("bb_kalender.html"), "https://www.boogie-baeren.de/kalender", TODAY)
    assert len(events) == 8
    workshop = next(e for e in events if "Halb-Akro" in e.title)
    assert workshop.type == "workshop"
    assert (workshop.start, workshop.end) == ("2026-10-17T10:00", "2026-10-17T16:00")
    assert workshop.url == "https://www.boogie-baeren.de/eventleser/Halb-Akro_Highlight-Figuren_17102026"
    multi = next(e for e in events if "MoosQuitos" in e.title)
    assert (multi.start, multi.end, multi.venue) == ("2026-10-17", "2026-10-18", None)


def test_boogie_baeren_pagination(make_ctx):
    ctx = make_ctx({
        "https://www.boogie-baeren.de/kalender": "bb_kalender.html",
        "https://www.boogie-baeren.de/training": "bb_training.html",
    })
    events = boogie_baeren.scrape({"id": "bb", "url": "https://www.boogie-baeren.de/", "params": {"max_pages": 2}}, ctx)
    assert ctx.http.calls[1] == ("https://www.boogie-baeren.de/kalender", {"page_e142": 2})
    assert ctx.http.calls[-1] == ("https://www.boogie-baeren.de/training", None)
    assert any(e.title == "Blues Open Level" for e in events)


def test_boogie_baeren_training_finds_blues_class():
    events = boogie_baeren.parse_training(fixture("bb_training.html"), "https://www.boogie-baeren.de/training", TODAY)
    assert len(events) > 50  # the whole grid of both cycles is parsed
    assert not any("Workshop" in e.title or "Clubabend" in e.title for e in events)  # in the calendar
    [course] = blues(events)
    assert (course.title, course.type) == ("Blues Open Level", "class")
    assert course.recurrence == "Tuesdays 20:45–22:15"
    assert (course.start, course.end) == ("2026-09-15T20:45", "2026-09-15T22:15")
    assert course.dates[0] == "2026-09-15" and course.dates[-1] == "2026-10-27" and len(course.dates) == 7
    assert course.venue == "Boogie-Bären Vereinsheim (Obergeschoss)"
    assert course.description.startswith("Teachers: Denise & Marcin.")


def test_boogie_baeren_training_skips_holidays_and_cancellations():
    events = boogie_baeren.parse_training(fixture("bb_training.html"), "https://www.boogie-baeren.de/training", TODAY)
    sunday = next(e for e in events if e.recurrence.startswith("Sundays") and e.dates[0] > "2026-09-14")
    assert "2026-11-01" not in sunday.dates  # Allerheiligen
    summer_friday = next(e for e in events if e.recurrence.startswith("Fridays 19:00") and e.dates[0] < "2026-09-14")
    assert "2026-09-11" not in summer_friday.dates  # "entfällt am 11.09."
    spanning = next(e for e in events if e.title == "Boogie Passion" and e.recurrence.startswith("Mondays"))
    assert spanning.recurrence == "Mondays 18:00–20:30"  # two slots, "Ab 18:00 Uhr"


# --- SwinginMunich.de (swing calendar) ---------------------------------------

SIM = "https://www.swinginmunich.de/"


def test_swinginmunich_listing():
    entries = swinginmunich.parse_listing(fixture("sim_kalender.html"), SIM + "de/kalender")
    assert len(entries) == 15
    assert entries[0] == (SIM + "de/node/2755/20261107", date(2026, 11, 7))


def test_swinginmunich_scrape_keeps_only_blues(make_ctx):
    ids = ["2608", "2710", "2711", "2733", "2749", "2750", "2755", "2763", "2767", "2774", "2775"]
    ctx = make_ctx({SIM + "de/kalender": "sim_kalender.html",
                    **{f"{SIM}de/node/{i}/": f"sim/node_{i}.html" for i in ids}})
    events = swinginmunich.scrape({"id": "sim", "url": SIM + "en", "params": {"max_pages": 1}}, ctx)
    assert len(events) == 15
    assert len(ctx.http.calls) == 1 + len(ids)  # recurring events share one detail page

    kept = blues(events)
    assert [(e.title, e.start) for e in kept] == [
        ("Bluesverschwörung Nr. 149", "2026-11-19T20:30"),
        ("Bluesverschwörung Nr. 150", "2026-12-03T20:30"),
    ]
    jam = kept[0]
    assert (jam.type, jam.venue, jam.address) == ("social", "Kongress Bar", "Theresienhöhe 15, 80339 München")
    assert jam.url == "https://kongressbar.de/events-live-bands-djs/"
    assert "Bluestanzen" in jam.description
    # The weekly Record Hop lists "Rhythm'n'Blues" in its description; that is not blues dancing
    record_hops = [e for e in events if e.title == "Fifties Record Hop"]
    assert record_hops and "Rhythm'n'Blues" in record_hops[0].description

# --- Venues & bands -----------------------------------------------------------

def test_unterfahrt_uses_local_time_and_detail_links():
    events = unterfahrt.parse(fixture("uf_programm.html"), "https://www.unterfahrt.de/programm.php")
    assert len(events) == 24
    first = events[0]
    assert first.title == "FABLES OF MINGUS"
    assert first.start == "2026-11-02T20:30"  # page says "MO•02•11•2026, 20••30"
    assert first.url.startswith("https://www.unterfahrt.de/programm-detail.php?dateID=")
    assert "#" not in first.url
    # November's jazz gigs only mention blues in passing: kept in loose mode, dropped in title mode
    assert {e.title for e in blues(events, "blues")} == {"FABLES OF MINGUS", "KAT EATON", "BOBBY SPARKS II"}
    assert blues(events, "blues_title") == []


def test_glockenbachwerkstatt_fishnblues():
    events = glockenbachwerkstatt.parse(fixture("gbw_fnb.html"), "https://www.glockenbachwerkstatt.de/veranstaltungen/", TODAY)
    assert len(events) == 8
    first = events[0]
    assert (first.title, first.start, first.type) == ("Louis Ville", "2026-10-21T20:30", "concert")
    assert first.url == "https://www.glockenbachwerkstatt.de/events/fishnblues-louis-ville1026/"
    assert "Fish'n Blues" in first.tags
    assert events[-1].start.startswith("2026-12-09")


def test_mfgigcal_band_dates_with_city_filter(make_ctx):
    url = "https://berndbauerbluesband.de/termine/"
    events = mfgigcal.parse(fixture("bbbb.html"), url)
    stormy = events[0]
    assert (stormy.title, stormy.start, stormy.venue) == (
        "Stormy Wednesday", "2026-10-21T20:00", "Kulturzentrum Giesinger Bahnhof")
    assert "81539" in stormy.address
    assert "offene Blues Session" in stormy.description

    ctx = make_ctx({url: "bbbb.html"})
    kept = mfgigcal.scrape({"id": "b", "url": url, "params": {"only_city": "Augsburg"}}, ctx)
    assert kept == []


# --- Generic adapters ---------------------------------------------------------

def test_ticketmaster_parse():
    data = {"_embedded": {"events": [{
        "name": "Joe Bonamassa", "url": "https://tm.example/e/1",
        "dates": {"start": {"localDate": "2027-03-01", "localTime": "20:00:00"}},
        "classifications": [{"genre": {"name": "Blues"}, "subGenre": {"name": "Undefined"}}],
        "_embedded": {"venues": [{"name": "Olympiahalle", "postalCode": "80809",
                                  "city": {"name": "München"}, "address": {"line1": "Spiridon-Louis-Ring 21"}}]},
    }]}}
    [e] = ticketmaster.parse(data)
    assert (e.title, e.start, e.venue, e.tags) == ("Joe Bonamassa", "2027-03-01T20:00", "Olympiahalle", ["Blues"])
    assert e.address == "Spiridon-Louis-Ring 21, 80809 München"


def test_ticketmaster_skips_without_key(make_ctx, monkeypatch):
    import pytest
    from scraper.registry import SkipSource
    monkeypatch.delenv("TICKETMASTER_API_KEY", raising=False)
    with pytest.raises(SkipSource):
        ticketmaster.scrape({"id": "tm", "url": "x"}, make_ctx())


def test_geohash_munich():
    assert ticketmaster.geohash(48.1372, 11.5755, 5) == "u281z"


def test_inmuenchen_parses_dates_venue_and_genres():
    events = {e.title: e for e in inmuenchen.parse(json.loads(fixture("inm_events.json")))}
    assert "Uferlos Festival" not in events  # "Aktuell keine Termine"
    karp = events["Inninger Bluestage 2026: Peter Karp Band + Ana Popovic"]
    assert (karp.start, karp.end, karp.tags) == ("2026-10-16T19:30", "2026-10-16T23:00", ["Blues"])
    assert (karp.venue, karp.address) == ("Alte Brauerei Stegen", "Landsberger Straße 57, 82266 Inning am Ammersee")
    night = events["Neuhauser Musiknacht"]
    assert (night.start, night.end, night.address) == ("2026-10-24T20:00", "2026-10-25T02:00", "80634 München")
    montack = events["Montack & The Ultimate Silverbeet"]
    assert (montack.venue, montack.end) == ("Drehleier – Szenerie", None)


def test_inmuenchen_keeps_blues_genre_or_title_only():
    kept = [e.title for e in inmuenchen.parse(json.loads(fixture("inm_events.json"))) if keep(e, "blues_title")]
    assert kept == ["Inninger Bluestage 2026: Peter Karp Band + Ana Popovic", "Montack & The Ultimate Silverbeet"]


def test_inmuenchen_stops_after_short_page(make_ctx):
    ctx = make_ctx({"https://www.in-muenchen.de/wp-json/": "inm_events.json"})
    events = inmuenchen.scrape({"id": "inm", "url": "https://www.in-muenchen.de/"}, ctx)
    assert len(events) == 4 and len(ctx.http.calls) == 1
    assert ctx.http.calls[0][1]["search"] == "blues"


def test_jsonld_events():
    payload = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "name": "ignored"},
        {"@type": "MusicEvent", "name": "Blues Night", "startDate": "2026-11-20T20:00:00+01:00",
         "url": "https://venue.example/blues-night",
         "location": {"@type": "Place", "name": "Venue",
                      "address": {"streetAddress": "Str. 1", "postalCode": "80331", "addressLocality": "München"}}},
    ]}
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    [e] = jsonld.parse(html, "https://venue.example/")
    assert (e.title, e.start, e.venue, e.address) == ("Blues Night", "2026-11-20T20:00", "Venue", "Str. 1, 80331 München")


def test_ical_expands_weekly_rule():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n"
        "BEGIN:VEVENT\r\nUID:1\r\nSUMMARY:Blues Social\r\n"
        "DTSTART;TZID=Europe/Berlin:20261007T200000\r\nDTEND;TZID=Europe/Berlin:20261007T230000\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=6\r\nLOCATION:Somewhere\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()
    events = ical.parse(ics, "social", TODAY, horizon_days=30)
    assert [e.start for e in events] == ["2026-10-21T20:00", "2026-10-28T20:00", "2026-11-04T20:00", "2026-11-11T20:00"]
    assert events[0].end == "2026-10-21T23:00"


RP = "https://rheinpfalz-schwabing.de/veranstaltungen/"


def test_rheinpfalz_schwabing_skips_closures_and_notices():
    events = rheinpfalz_schwabing.parse(fixture("rp_events.html"), RP, TODAY)
    titles = [e.title for e in events]
    assert len(events) == 17
    assert not [t for t in titles if "geschlossen" in t.lower() or "trauern" in t]
    first = events[0]
    assert (first.title, first.start, first.end, first.type) == ("Beat Stones", "2026-10-17T20:00", None, "concert")
    assert first.venue == "Rheinpfalz Schwabing" and first.url == RP
    # "20:00 – 20:00" on a private event must not become a zero-length end
    assert all(e.end is None for e in events)


def test_rheinpfalz_schwabing_blues_filter_keeps_blues_gigs():
    events = rheinpfalz_schwabing.parse(fixture("rp_events.html"), RP, TODAY)
    kept = {e.title for e in events if keep(e, "blues")}
    assert {"Back To Zero", "Blue Traces", "Jakarta Blues Band", "Black Patti"} <= kept
    assert not kept & {"Beat Stones", "Roda de choro", "Skillgang"}
