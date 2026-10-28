from scraper.adapters import truderinger_kulturkreis as tkk
from scraper.filters import keep

from .conftest import TODAY, fixture

URL = "https://www.truderingerkulturkreis.de/"


def test_truderinger_kulturkreis_events():
    events = tkk.parse(fixture("tkk_home.html"), URL, TODAY)
    assert [(e.start, e.title) for e in events] == [
        ("2026-10-11T12:00", "Motovidlo"),
        ("2026-12-31T19:00", "Silvesterkonzert"),
        ("2027-01-24T17:00", "HaberJazzBand"),
    ]  # past events below "Und das war schon...." are skipped
    haber = events[-1]
    assert haber.venue == "Kulturzentrum Trudering" and haber.url == URL
    assert "Blues, Dixieland und Swing" in haber.description
    assert not haber.description.startswith("24.1.27")


def test_truderinger_kulturkreis_blues_filter():
    events = tkk.parse(fixture("tkk_home.html"), URL, TODAY)
    assert [e.title for e in events if keep(e, "blues")] == ["HaberJazzBand"]
