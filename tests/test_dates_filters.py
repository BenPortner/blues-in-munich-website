from datetime import date

from scraper.dates import find_dates, find_time_range
from scraper.filters import is_blues, keep
from scraper.models import Event, guess_type

T = date(2026, 10, 16)


def test_long_german_date():
    assert find_dates("Samstag, 17. Oktober 2026") == [date(2026, 10, 17)]


def test_two_days_share_trailing_year():
    assert find_dates("Samstag, 31. Oktober und Sonntag, 1. November 2026") == [
        date(2026, 10, 31), date(2026, 11, 1)]


def test_numeric_range_with_year_at_end():
    assert find_dates("Freitag, 23.10. – Sonntag, 25.10.2026") == [date(2026, 10, 23), date(2026, 10, 25)]


def test_slash_separated_days():
    assert find_dates("21./28. Oktober + 04./11. November", default_year=2026) == [
        date(2026, 10, 21), date(2026, 10, 28), date(2026, 11, 4), date(2026, 11, 11)]


def test_year_wrap_going_backwards():
    assert find_dates("Montag, 14. Dezember – Freitag, 15. Januar 2027") == [
        date(2026, 12, 14), date(2027, 1, 15)]


def test_missing_year_is_inferred_forward():
    assert find_dates("21.10.", today=T) == [date(2026, 10, 21)]
    assert find_dates("13.1.", today=T) == [date(2027, 1, 13)]


def test_non_dates_are_ignored():
    assert find_dates("Swing Übungsabend 10.26 mit Live Musik", today=T) == []
    assert find_dates("Sonntag, XX. November 2026") == []
    assert find_dates("immer am Sonntag!") == []


def test_time_range():
    assert find_time_range("Sonntag, 18. Oktober 2026 | 13:00–14:30 Uhr") == ("13:00", "14:30")
    assert find_time_range("20:30 Uhr") == ("20:30", None)
    assert find_time_range("17.10.2026") == (None, None)


def test_blues_keywords():
    assert is_blues("Blues · alle Level")
    assert is_blues("Fish'n Blues Konzert")
    assert is_blues("Bluesrock aus Chicago")


def test_rhythm_and_blues_is_not_blues_dance():
    assert not is_blues("Rock'n'Roll, Boogie Woogie, Rockabilly, Jive, Bop, Rhythm'n'Blues")
    assert not is_blues("Musik von Rhythm’n’Blues und Rock’n’Roll")
    assert not is_blues("Jazz, Funk, Fusion, R & B, Soul")
    assert not is_blues("Follow us on Bluesky")


def test_exclude_patterns():
    assert not is_blues("Blues Brothers Tribute", exclude=["tribute"])


def test_filter_modes():
    e = Event(title="Kat Eaton", type="concert", start="2026-11-03",
              description="Songs zwischen Soul, Blues, Jazz und Gospel")
    assert keep(e, "blues")
    assert not keep(e, "blues_title")
    assert keep(Event(title="X", type="concert", start="2026-11-03", tags=["Blues"]), "blues_title")
    assert keep(e, "none")


def test_guess_type():
    assert guess_type("Workshop-Weekend mit Nicholas", "workshop") == "workshop"
    assert guess_type("Halb-Akro Workshop", "social") == "workshop"
    assert guess_type("West Coast Swing Party", "class") == "social"
    assert guess_type("Something", "concert") == "concert"
