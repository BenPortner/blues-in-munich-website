from scraper.__main__ import dedupe, same_event
from scraper.models import Event


def ev(title, start="2026-10-21T20:00", venue="Kulturzentrum Giesinger Bahnhof", **kw):
    return Event(title=title, type=kw.pop("type", "concert"), start=start, venue=venue,
                 id=kw.pop("id", title), **kw)


BAND = "Bernd Bauer Blues Band: Stormy Wednesday"


def test_differently_titled_listings_of_one_session():
    assert same_event(ev(BAND), ev("Session Stormy Wednesday"))
    assert same_event(ev("Stephan Zinner", venue="Schlachthof"),
                      ev("Stephan Zinner – Großstadtblues", venue="Schlachthof – Saal"))
    # apostrophes and a different start time (20:00 vs 20:15) don't make two listings different
    assert same_event(ev("William’s Wetsox", venue="Rheinpfalz Schwabing", start="2026-10-24T20:00"),
                      ev("Williams Wetsox", venue="Rheinpfalz Schwabing", start="2026-10-24T20:15"))
    # no venue on one side: the start time has to match instead
    assert same_event(ev(BAND, venue=None), ev("Session Stormy Wednesday"))
    assert not same_event(ev(BAND, venue=None), ev("Session Stormy Wednesday", start="2026-10-21T21:00"))


def test_different_events_stay_apart():
    assert not same_event(ev(BAND), ev("Session Stormy Wednesday", start="2026-11-18T20:00"))  # other day
    assert not same_event(ev(BAND), ev("Session Stormy Wednesday", venue="Unterfahrt"))       # other place
    assert not same_event(ev("Louis Ville"), ev("Pete Gavin"))                                # other act
    # titles of nothing but filler say nothing about which event it is
    assert not same_event(ev("Bernd Bauer Blues Band: Live-Konzert"), ev("Blues Session live"))


def test_generic_series_listing_yields_to_the_specific_one():
    series = ev("Inninger Bluestage 2026", id="a", venue="Groundlift Ammersee Live Studios",
                address="Landsberger Straße 57, 82266 Stegen/Inning am Ammersee", start="2026-10-17T19:30")
    night = ev("Inninger Bluestage 2026: Chris Kramer + Al Jones Band", id="b", venue="Alte Brauerei Stegen",
               address="Landsberger Straße 57, 82266 Inning am Ammersee", start="2026-10-17T19:30",
               end="2026-10-17T23:00")
    assert [e.id for e in dedupe([series, night])] == ["b"]
    assert [e.id for e in dedupe([night, series])] == ["b"]


def test_dedupe_keeps_first_source_and_fills_gaps():
    band = ev(BAND, id="a", description="Akustische offene Blues Session, Eintritt frei")
    listing = ev("Session Stormy Wednesday", id="b", end="2026-10-21T22:30", address="Giesinger Bahnhofplatz 1",
                 description="Long magazine blurb")
    other = ev("Louis Ville", id="c", venue="Glockenbachwerkstatt")
    result = dedupe([band, listing, other])
    assert [e.id for e in result] == ["a", "c"]
    kept = result[0]
    assert kept.title == BAND
    assert kept.end == "2026-10-21T22:30" and kept.address == "Giesinger Bahnhofplatz 1"  # taken over
    assert kept.description == "Akustische offene Blues Session, Eintritt frei"          # not overwritten
