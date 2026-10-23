import json
from datetime import timedelta

import requests

from scraper.artists import API, Artist, LastFm, act_keys, enrich, find_artists

from .conftest import TODAY

LISTENERS = {"Ana Popovic": 79400, "Peter Karp": 9000, "B.B. & The Blues Shacks": 30000,
             "Ludwig Seuss": 4000, "Abi Wallenstein": 8000, "Devon Allman": 60000, "Joe Bonamassa": 1_200_000}


def known(name):
    for artist, listeners in LISTENERS.items():
        if artist.lower() == name.lower():
            return Artist(artist, listeners)
    return None


def asked(title, **kw):
    names = []
    find_artists(title, lambda n: names.append(n), **kw)
    return names


def test_find_artists_splits_bills():
    found = find_artists("Inninger Bluestage 2026: Peter Karp Band + Ana Popovic", known)
    assert found == [Artist("Peter Karp", 9000), Artist("Ana Popovic", 79400)]


def test_find_artists_keeps_band_names_with_ampersand():
    assert find_artists("B.B. & The Blues Shacks", known) == [Artist("B.B. & The Blues Shacks", 30000)]
    assert asked("B.B. & The Blues Shacks")[0] == "B.B. & The Blues Shacks"


def test_find_artists_tries_names_without_apostrophes():
    assert asked("William’s Wetsox") == ["William’s Wetsox", "Williams Wetsox"]
    assert asked("Williams Wetsox Trio") == ["Williams Wetsox Trio", "Williams Wetsox"]


def test_find_artists_lists_and_programme_titles():
    title = "30. Münchner Bluesnacht mit Zither Manä, Abi Wallenstein, Ludwig Seuss & Band"
    assert [a.name for a in find_artists(title, known)] == ["Abi Wallenstein", "Ludwig Seuss"]
    assert asked("Stephan Zinner – Der Teufel, das Mädchen, der Blues und ich") == ["Stephan Zinner"]
    assert asked("Bernd Bauer Blues Band: Live-Konzert") == ["Bernd Bauer Blues Band", "Bernd Bauer Blues"]


def test_act_keys():
    assert act_keys("Günter Grünwald & Rad Gumbo") == {"gunter-grunwald-and-rad-gumbo", "gunter-grunwald", "rad-gumbo"}
    assert {"gunter-grunwald", "rad-gumbo"} <= act_keys("Rad Gumbo und Günter Grünwald")
    assert "ludwig-seuss" in act_keys("Ludwig Seuss & Band") & act_keys("Ludwig Seuss Band")
    assert "munich-rhythm-and-blues-band" in act_keys("Munich Rhythm & Blues Band")
    assert act_keys("Stephan Zinner – Großstadtblues") == {"stephan-zinner"}
    assert act_keys("Blues Band") == set()  # too generic to link two listings


def test_find_artists_skips_genre_names():
    assert asked("Anni und Hans: Blues & Jazz") == ["Anni und Hans"]
    assert asked("Rock 'n' Roll & Boogie") == []
    assert asked("Blues Pills") == ["Blues Pills"]  # one real word is enough


def test_find_artists_skips_event_words_and_single_names():
    assert asked("Inninger Bluestage 2026") == []
    assert asked("Session Stormy Wednesday") == []
    assert asked("13. American Bar Night – „Midlife or Crisis?“ & Friends") == []
    assert "Johnny" not in asked("Johnny & The Yooahoos")
    assert asked("Eric Bibb", ignore={"eric-bibb"}) == []


class FakeLastFm:
    def __init__(self, listeners=LISTENERS, fail=False):
        self.listeners = listeners
        self.fail = fail
        self.calls = []

    def json(self, url, params=None):
        assert url == API and params["method"] == "artist.getInfo" and params["autocorrect"] == 0
        self.calls.append(params["artist"])
        if self.fail:
            raise requests.ConnectionError("down")
        hit = known(params["artist"])
        if not hit:
            return {"error": 6, "message": "The artist you supplied could not be found"}
        return {"artist": {"name": hit.name, "url": f"https://www.last.fm/music/{hit.name.replace(' ', '+')}", "stats": {"listeners": str(hit.listeners), "playcount": "1"}}}


def test_lastfm_caches_and_refreshes():
    http, cache = FakeLastFm(), {}
    lastfm = LastFm(http, "key", cache, TODAY)
    assert lastfm("Ana Popovic") == Artist("Ana Popovic", 79400)
    assert lastfm("Nobody Here") is None
    assert lastfm("ana popovic") == Artist("Ana Popovic", 79400)
    assert http.calls == ["Ana Popovic", "Nobody Here"]
    assert cache["nobody-here"] == {"name": None, "listeners": 0, "checked": TODAY.isoformat()}

    later = LastFm(http, "key", cache, TODAY + timedelta(days=31))
    later("Ana Popovic")
    assert http.calls[-1] == "Ana Popovic"  # stale entry looked up again


def test_lastfm_without_key_or_after_failure_uses_cache():
    cache = {"ana-popovic": {"name": "Ana Popovic", "listeners": 70000, "checked": "2026-01-01"}}
    http = FakeLastFm()
    assert LastFm(http, None, cache, TODAY)("Ana Popovic") == Artist("Ana Popovic", 70000)
    assert http.calls == []

    broken = FakeLastFm(fail=True)
    lastfm = LastFm(broken, "key", cache, TODAY)
    assert lastfm("Ana Popovic") == Artist("Ana Popovic", 70000)  # stale, but better than nothing
    assert lastfm("Joe Bonamassa") is None
    assert broken.calls == ["Ana Popovic"]  # stops asking after the first failure


def test_lastfm_aliases():
    http = FakeLastFm()
    lastfm = LastFm(http, "key", {}, TODAY, aliases={"Devon Allman Blues Summit": "Devon Allman"})
    title = "Devon Allman Blues Summit feat. Jimmy Hall, Claudette King, Bernard Allison"
    assert find_artists(title, lastfm) == [Artist("Devon Allman", 60000)]


def test_lastfm_links():
    links = {"Ana Popovic": "https://anapopovic.com/", "Louis Ville": "https://www.last.fm/music/Louis+Ville+(DE)"}
    lastfm = LastFm(FakeLastFm(), "key", {}, TODAY, links=links)
    ana = lastfm("ana popovic")
    assert (ana.name, ana.listeners, ana.url) == ("Ana Popovic", 79400, "https://anapopovic.com/")
    louis = lastfm("Louis Ville")  # unknown to Last.fm, linked anyway
    assert (louis.name, louis.listeners, louis.url) == ("Louis Ville", 0, links["Louis Ville"])
    assert lastfm("Joe Bonamassa").url == "https://www.last.fm/music/Joe+Bonamassa"


def test_enrich(tmp_path):
    settings = tmp_path / "highlights.yaml"
    settings.write_text("artists:\n  min_listeners: 50000\n  ignore: [Peter Karp]\n", encoding="utf-8")
    cache_path = tmp_path / "data" / "artists.json"
    events = [
        {"title": "Inninger Bluestage 2026: Peter Karp Band + Ana Popovic", "type": "concert"},
        {"title": "Joe Bonamassa", "type": "concert"},
        {"title": "Ludwig Seuss Band", "type": "concert"},           # known, but below the cutoff
        {"title": "Some Local Band", "type": "concert"},
        {"title": "Ana Popovic workshop", "type": "workshop"},
    ]
    enrich(events, FakeLastFm(), "key", cache_path, settings, TODAY)
    assert [e.get("known_artists") for e in events] == [["Ana Popovic"], ["Joe Bonamassa"], [], [], None]
    assert events[0]["artists"] == [{"name": "Ana Popovic", "url": "https://www.last.fm/music/Ana+Popovic"}]
    assert events[2]["artists"] == [{"name": "Ludwig Seuss", "url": "https://www.last.fm/music/Ludwig+Seuss"}]
    assert events[3]["artists"] == [] and "artists" not in events[4]
    # Events carry the names only; listener counts stay in the (unpublished) cache
    assert not any("listeners" in e or "artist" in e for e in events)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "peter-karp" not in cache and cache["ana-popovic"]["listeners"] == 79400

    # Names no longer on any bill drop out of the cache
    enrich(events[1:2], FakeLastFm(), "key", cache_path, settings, TODAY)
    assert list(json.loads(cache_path.read_text(encoding="utf-8"))) == ["joe-bonamassa"]


def test_enrich_without_key_or_cache(tmp_path):
    events = [{"title": "Joe Bonamassa", "type": "concert"}]
    enrich(events, FakeLastFm(), None, tmp_path / "artists.json", tmp_path / "missing.yaml", TODAY)
    assert events[0]["known_artists"] == [] and events[0]["artists"] == []


def test_profile_url_for_old_cache_entries():
    cache = {"b-b-the-blues-shacks": {"name": "B.B. & The Blues Shacks", "listeners": 2873, "checked": TODAY.isoformat()}}
    hit = LastFm(FakeLastFm(), None, cache, TODAY)("B.B. & The Blues Shacks")
    assert hit.url == "https://www.last.fm/music/B.B.+%26+The+Blues+Shacks"


def test_enrich_keeps_every_known_act(tmp_path):
    settings = tmp_path / "highlights.yaml"
    settings.write_text("artists:\n  min_listeners: 50000\n", encoding="utf-8")
    events = [{"title": "Ana Popovic + Peter Karp + Joe Bonamassa + Ana Popovic", "type": "concert"}]
    enrich(events, FakeLastFm(), "key", tmp_path / "artists.json", settings, TODAY)
    assert events[0]["known_artists"] == ["Joe Bonamassa", "Ana Popovic"]
    assert [a["name"] for a in events[0]["artists"]] == ["Ana Popovic", "Peter Karp", "Joe Bonamassa"]  # bill order, no repeats


def test_repo_highlights_yaml_has_artist_settings():
    from scraper.__main__ import ROOT
    from scraper.artists import load_settings
    settings = load_settings(ROOT / "highlights.yaml")
    assert settings["min_listeners"] > 0
    assert "devon-allman-blues-summit" in {k.lower().replace(" ", "-") for k in settings["aliases"]}
