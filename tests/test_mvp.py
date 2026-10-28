from scraper.adapters import mvp
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://www.mvp.de/"
LISTING = "https://www.mvp.de/muenchen/veranstaltungen/konzert-jazz/"
DETAIL = "https://www.mvp.de/muenchen/veranstaltungen/blues-briederchen-blues-brothers-tribute-schlachthof-saal/"


def test_mvp_listing():
    events = mvp.parse(fixture("mvp_jazz.html"), LISTING, TODAY)
    assert len(events) == 40
    zinner = next(e for e in events if e.title.startswith("Stephan Zinner"))
    assert zinner.title == "Stephan Zinner - Der Teufel, das Mädchen, der Blues und ich"  # "- MÜNCHEN" dropped
    assert (zinner.start, zinner.venue) == ("2026-12-01", "Schlachthof - Saal")
    gauting = [e for e in events if "Gautinger" in e.title]
    assert {(e.title, e.venue) for e in gauting} == {("11. Gautinger Bluesnacht", "bosco - Großer Saal, Gauting")}


def test_mvp_blues_filter():
    events = mvp.parse(fixture("mvp_jazz.html"), LISTING, TODAY)
    kept = [e.title for e in events if keep(e, "blues_title")]
    assert "Blues Briederchen® - Blues Brothers Tribute" in kept and "The Hot Stuff Jazzband" not in kept


def test_mvp_scrape_reads_details_of_blues_listings(make_ctx):
    ctx = make_ctx({LISTING: "mvp_jazz.html", DETAIL: "mvp_briederchen.html",
                    "https://www.mvp.de/": "mvp_briederchen.html"})  # other detail pages: any page will do
    events = mvp.scrape({"id": "mvp", "url": URL}, ctx)
    blues = next(e for e in events if "Briederchen" in e.title)
    assert (blues.start, blues.address) == ("2027-02-09T20:00", "Zenettistraße 9, 80337 München")
    detail_calls = [url for url, _ in ctx.http.calls if url != LISTING]
    assert DETAIL in detail_calls and len(detail_calls) == sum(1 for e in events if keep(e, "blues_title"))
