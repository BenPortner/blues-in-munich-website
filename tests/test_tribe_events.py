import json

from scraper.adapters import tribe_events
from scraper.filters import keep

from .conftest import fixture

URL = "https://ackermannbogen-ev.de/programm-alles"
API = "https://ackermannbogen-ev.de/wp-json/tribe/events/v1/events"


def test_tribe_events():
    events = tribe_events.parse(json.loads(fixture("ackermannbogen_events.json")))
    soul = next(e for e in events if e.title == "Be My Guest - Soul Charade")
    assert (soul.start, soul.end, soul.type) == ("2026-10-13T20:00", "2026-10-13T22:00", "concert")
    assert soul.url == "https://ackermannbogen-ev.de/programm/be-my-guest-soul-charade/"
    assert soul.venue == "KreativGarage Studio"
    assert soul.address == "Rosa-Aschenbrenner-Bogen 9 / UG, 80797 München"
    assert soul.description.startswith("Tom Reinbrecht") and soul.description.endswith("27,00€")
    assert "BluesJazz" in soul.tags
    assert any(e.title == "tanzbar – DIE Party im Ackermannbogen" for e in events)


def test_tribe_events_blues_filter():
    events = tribe_events.parse(json.loads(fixture("ackermannbogen_events.json")))
    kept = [e.title for e in events if keep(e, "blues_title")]
    assert kept == ["Be My Guest - Soul Charade"]


def test_tribe_events_scrape(make_ctx):
    ctx = make_ctx({API: "ackermannbogen_events.json"})
    source = {"id": "ackermannbogen", "url": URL, "params": {"categories": ["musik", "musik-gesang"]}}
    events = tribe_events.scrape(source, ctx)
    assert events and ctx.http.calls == [
        (API, {"per_page": 50, "categories": "musik,musik-gesang", "page": 1})]
