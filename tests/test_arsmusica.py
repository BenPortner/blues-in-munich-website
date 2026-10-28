from scraper.adapters import arsmusica
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://www.ars-musica-muenchen.de/"
LISTING = "https://www.ars-musica-muenchen.de/events.php?shortlisting=true"


def test_arsmusica_events():
    events = arsmusica.parse(fixture("arsmusica_events.html"), LISTING, TODAY)
    assert len(events) == 14
    friday = next(e for e in events if e.title == "That Friday Feeling")
    assert (friday.start, friday.type) == ("2026-10-29T19:30", "concert")
    assert friday.url == "https://www.ars-musica-muenchen.de/event_details.php?id=2586&title=That%20Friday%20Feeling"
    assert friday.venue == "Salettl im Tannengarten"
    assert friday.address == "Pfeuferstraße 32, 81373 München"
    assert friday.tags == ["Singer-/Songwriter Blues Folk"]
    assert friday.description.startswith("Hinter dem Namen") and friday.description.endswith("Robert Richter.")
    delta = next(e for e in events if e.title.startswith("Delta X"))
    assert delta.address == "Pfeuferstr. 32, 81377 München"
    saw = next(e for e in events if e.title.startswith("Singende Säge"))
    assert (saw.start, saw.type) == ("2026-11-14T14:00", "other")  # an instrument course, not dancing


def test_arsmusica_blues_filter():
    events = arsmusica.parse(fixture("arsmusica_events.html"), LISTING, TODAY)
    kept = [e.title for e in events if keep(e, "blues")]
    assert kept == ["That Friday Feeling", "Matching Ties Duo & Special Guest Rosena Horan-Irland"]


def test_arsmusica_scrape(make_ctx):
    ctx = make_ctx({LISTING: "arsmusica_events.html"})
    events = arsmusica.scrape({"id": "ars-musica", "url": URL}, ctx)
    assert events and ctx.http.calls == [(LISTING, None)]
