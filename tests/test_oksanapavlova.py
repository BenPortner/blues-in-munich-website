import json

from scraper.adapters import oksanapavlova
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://oksanapavlova.de/"
API = "https://oksanapavlova.de/wp-json/wp/v2/posts"


def test_oksanapavlova_posts():
    events = oksanapavlova.parse(fixture("op_posts.json"))
    assert len(events) == 16  # 20 posts; 4 have no date on/after publishing ("Danke!!!", news)
    assert not any(e.title == "Danke!!!" for e in events)
    first = events[0]
    assert (first.title, first.start, first.type) == (
        "08.11.26 Lindy Hop – Taster und Workshops", "2026-11-08T11:00", "workshop")
    assert first.url == "https://oksanapavlova.de/aktuelles/08-11-26-lindy-hop-taster-und-workshops/"

    blues = [e for e in events if keep(e, "blues")]
    assert [(e.title, e.start, e.end) for e in blues] == [
        ("Blues Workshop am 11.07.2026", "2026-07-11T12:00", "2026-07-11T15:00"),
        ("Blues Workshop am 16. Mai 2026", "2026-05-16T16:00", "2026-05-16T19:00"),
        ("Blues Workshop am 07. März 2026 von 16:00 bis 19:00", "2026-03-07T16:00", "2026-03-07T19:00"),
    ]
    assert blues[0].address == "Arnulfstr. 195, 1. OG"
    assert "David C. Tritel" in blues[0].description
    # all fixture blues workshops are past on the capture day; the runner drops them
    assert not [e for e in blues if e.last_date >= TODAY.isoformat()]


def test_oksanapavlova_year_from_publish_date():
    post = {
        "date": "2026-12-01T09:00:00", "link": URL + "aktuelles/blues/",
        "title": {"rendered": "Blues Workshop im Januar"},
        "content": {"rendered": "<p>Wann: 17. Januar, 14:00 &#8211; 17:00 Uhr</p><p>Wo: Arnulfstr. 195, 1. OG</p>"
                               "<p>Preis: 50 EUR</p>"},
    }
    [event] = oksanapavlova.parse(json.dumps([post]))
    assert (event.start, event.end, event.address) == ("2027-01-17T14:00", "2027-01-17T17:00", "Arnulfstr. 195, 1. OG")


def test_oksanapavlova_scrape(make_ctx):
    ctx = make_ctx({API: "op_posts.json"})
    events = oksanapavlova.scrape({"id": "oksana-pavlova", "url": URL, "default_type": "workshop"}, ctx)
    assert len(events) == 16
    assert ctx.http.calls == [(API, {"per_page": 20, "_fields": "id,date,link,title,content"})]
