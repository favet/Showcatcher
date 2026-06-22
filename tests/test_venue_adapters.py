"""Phase 8.3 — venue-direct scraper tests.

Each venue adapter parses its committed fixture into RawEvents whose ticket_url
points at the venue's real (non-Ticketmaster) ticketer. Runs offline.
"""
from datetime import date
from datetime import time as dt_time
from pathlib import Path

from showcat.adapters.sources.custom.aladdin import AladdinAdapter
from showcat.adapters.sources.custom.mcmenamins import CrystalBallroomAdapter
from showcat.adapters.sources.custom.rhp import (
    HawthorneAdapter,
    RoselandAdapter,
    WonderBallroomAdapter,
)
from showcat.adapters.sources.custom.truewest import TrueWestAdapter
from showcat.adapters.tickets.providers import classify_provider

FIXTURES = Path(__file__).parent / "fixtures" / "venues"


def _parse_fixture(adapter: object, name: str) -> list:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return adapter.parse(html)  # type: ignore[attr-defined]


def _assert_all_etix(events: list) -> None:
    assert events, "fixture should yield events"
    for e in events:
        assert classify_provider(e.ticket_url) == "etix", f"{e.headliner!r}: {e.ticket_url}"
        assert "ticketmaster.com" not in (e.ticket_url or "")


class TestAladdinAdapter:
    def _events(self) -> list:
        html = (FIXTURES / "aladdin.html").read_text(encoding="utf-8")
        return AladdinAdapter().parse(html)

    def test_parses_multiple_events(self) -> None:
        events = self._events()
        assert len(events) >= 5

    def test_all_links_are_etix_not_ticketmaster(self) -> None:
        events = self._events()
        assert events, "fixture should yield events"
        for e in events:
            assert classify_provider(e.ticket_url) == "etix", (
                f"{e.headliner!r} link is not Etix: {e.ticket_url}"
            )
            assert "ticketmaster.com" not in (e.ticket_url or "")

    def test_event_fields_populated(self) -> None:
        events = self._events()
        e = next(ev for ev in events if ev.headliner == "American Aquarium")
        assert e.event_date == date(2026, 9, 19)
        assert e.show_time == dt_time(20, 0)
        assert e.venue == "Aladdin Theater"
        assert e.source == "aladdin_theater"
        assert e.source_id  # stable, non-empty

    def test_source_ids_unique(self) -> None:
        events = self._events()
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))


class TestRoselandAdapter:
    def test_parses_etix_events_with_times(self) -> None:
        events = _parse_fixture(RoselandAdapter(), "roseland.html")
        _assert_all_etix(events)
        assert len(events) >= 3
        olp = next(e for e in events if "Our Lady Peace" in e.headliner)
        assert olp.event_date == date(2026, 6, 23)
        assert olp.show_time == dt_time(20, 0)
        assert olp.doors_time == dt_time(19, 0)
        assert olp.venue == "Roseland Theater"


class TestHawthorneAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(HawthorneAdapter(), "hawthorne.html")
        _assert_all_etix(events)
        assert all(e.venue == "Hawthorne Theatre" for e in events)
        assert all(e.source == "hawthorne_theatre" for e in events)


class TestWonderAdapter:
    def test_parses_etix_events_month_view(self) -> None:
        # Wonder's /events/ uses RHP's month-view field classes (eventTitleDiv,
        # dateEvent, eventDoorStartDate) — the adapter handles both variants.
        events = _parse_fixture(WonderBallroomAdapter(), "wonder.html")
        _assert_all_etix(events)
        assert all(e.venue == "Wonder Ballroom" for e in events)
        assert all(e.event_date is not None for e in events)


class TestTrueWestAdapter:
    def test_parses_etix_events_and_venue_from_logo(self) -> None:
        events = _parse_fixture(TrueWestAdapter(), "truewest.html")
        _assert_all_etix(events)
        # Combined feed distinguishes Mississippi Studios vs Polaris Hall.
        venues = {e.venue for e in events}
        assert venues & {"Mississippi Studios", "Polaris Hall"}
        for e in events:
            assert e.event_date is not None


class TestCrystalBallroomAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(CrystalBallroomAdapter(), "crystal.html")
        _assert_all_etix(events)
        assert all(e.venue == "Crystal Ballroom" for e in events)
        assert all(e.source == "crystal_ballroom" for e in events)
        assert all(e.event_date is not None for e in events)
