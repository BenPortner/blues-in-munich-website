from scraper.adapters import hepcat
from scraper.filters import keep

from .conftest import fixture

URL = "https://hepcatclub.com/"
AJAX = "https://hepcatclub.com/wp-admin/admin-ajax.php"


def test_hepcat_calendar():
    events = hepcat.parse(fixture("hepcat_ajax.html"), URL)
    blues = [e for e in events if e.title == "Blues 2 mit Clara"]
    # the weekly class, in blocks split at the Christmas and Easter breaks
    assert [(e.start, e.dates[-1], len(e.dates)) for e in blues] == [
        ("2026-10-06T19:35", "2026-12-15", 11), ("2027-01-12T19:35", "2027-03-16", 10),
        ("2027-04-06T19:35", "2027-09-28", 25)]
    first = blues[0]
    assert (first.type, first.end, first.recurrence) == ("class", "2026-10-06T20:35", "Tuesdays 19:35–20:35")
    assert (first.venue, first.address, first.url) == ("Hep Cat Club", "Viktoriastraße 3b, 86150 Augsburg", URL)

    by_title = {e.title: e for e in events}
    # feeds give the type; a multi-day festival is one event, its exclusive end made inclusive
    fest = by_title["XmaSwing Festival (Lindy Hop & Solo Jazz)"]
    assert (fest.type, fest.start, fest.end) == ("workshop", "2026-12-11", "2026-12-13")
    party = by_title["Honky Tonk im Hep Cat Club: Martha Miller & The Jitterbugs (live)"]
    assert (party.type, party.start) == ("social", "2026-11-07T19:00")
    assert party.description.startswith("Beim Honky Tonk")
    taster = by_title["Shuffle Dance Schnupperkurs - Tag der offenen Tür"]
    assert (taster.type, taster.dates) == ("class", [])

    # only the blues class has blues in its title
    assert {e.title for e in events if keep(e, "blues_title")} == {"Blues 2 mit Clara"}


def test_hepcat_scrape(make_ctx):
    ctx = make_ctx({AJAX: "hepcat_ajax.html", URL: "hepcat_home.html"})
    events = hepcat.scrape({"id": "hepcat-club", "url": URL}, ctx)
    assert len(events) == 8
    page, ajax = ctx.http.calls
    assert page == (URL, None)
    assert ajax[0] == AJAX
    assert ajax[1] == {"action": "r34ics_ajax", "r34ics_nonce": "83dbfb23bf", "subaction": "display_calendar",
                       "args": "ceaa9adea52596c22f53bcc3966cc7b17e315122", "js_args": '{"debug":null}',
                       "ym": "202610"}
