"""Venue-direct scraper tests (Phase 8.3 + Phase 9 venue expansion).

Each venue adapter parses its committed fixture into RawEvents whose ticket_url
points at the venue's real (non-Ticketmaster) ticketer. Runs offline.
"""
from datetime import date
from datetime import time as dt_time
from pathlib import Path

from showcat.adapters.sources.custom.aladdin import AladdinAdapter
from showcat.adapters.sources.custom.mcmenamins import CrystalBallroomAdapter
from showcat.adapters.sources.custom.mcmenamins_main import (
    AlsDenAdapter,
    EdgefieldAdapter,
    LolasRoomAdapter,
    WhiteEagleAdapter,
)
from showcat.adapters.sources.custom.getdown import GetDownAdapter
from showcat.adapters.sources.custom.revhall import RevolutionHallAdapter
from showcat.adapters.sources.custom.rhp import (
    AlbertaRoseAdapter,
    HawthorneAdapter,
    HoloceneAdapter,
    RoselandAdapter,
    WonderBallroomAdapter,
)
from showcat.adapters.sources.custom.showdown import ShowdownAdapter
from showcat.adapters.sources.custom.novapdx import NovaPdxAdapter
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


class TestRevolutionHallAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(RevolutionHallAdapter(), "revhall.html")
        _assert_all_etix(events)
        assert all(e.event_date is not None for e in events)
        assert all(e.source == "revolution_hall" for e in events)

    def test_distinguishes_show_bar_venue(self) -> None:
        events = _parse_fixture(RevolutionHallAdapter(), "revhall.html")
        venues = {e.venue for e in events}
        # Fixture has both Revolution Hall and Show Bar events
        assert "Revolution Hall" in venues
        assert "Show Bar" in venues

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(RevolutionHallAdapter(), "revhall.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))


class TestWhiteEagleAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(WhiteEagleAdapter(), "whiteeagle.html")
        _assert_all_etix(events)
        assert all(e.venue == "White Eagle Saloon" for e in events)
        assert all(e.event_date is not None for e in events)


class TestAlsDenAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(AlsDenAdapter(), "alsden.html")
        _assert_all_etix(events)
        assert all(e.venue == "Al's Den" for e in events)
        assert all(e.event_date is not None for e in events)


class TestLolasRoomAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(LolasRoomAdapter(), "lolasroom.html")
        _assert_all_etix(events)
        assert all(e.venue == "Lola's Room" for e in events)
        assert all(e.event_date is not None for e in events)


class TestEdgefieldAdapter:
    def test_parses_etix_concert_events(self) -> None:
        events = _parse_fixture(EdgefieldAdapter(), "edgefield.html")
        _assert_all_etix(events)
        assert all(e.venue == "Edgefield Amphitheater" for e in events)
        assert all(e.event_date is not None for e in events)


# Phase 9 — venue expansion


class TestAlbertaRoseAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(AlbertaRoseAdapter(), "alberta_rose.html")
        _assert_all_etix(events)
        assert all(e.venue == "Alberta Rose Theatre" for e in events)
        assert all(e.source == "alberta_rose" for e in events)
        assert all(e.event_date is not None for e in events)

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(AlbertaRoseAdapter(), "alberta_rose.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))


class TestHoloceneAdapter:
    def test_parses_etix_events(self) -> None:
        events = _parse_fixture(HoloceneAdapter(), "holocene.html")
        _assert_all_etix(events)
        assert all(e.venue == "Holocene" for e in events)
        assert all(e.source == "holocene" for e in events)
        assert all(e.event_date is not None for e in events)

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(HoloceneAdapter(), "holocene.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))


class TestGetDownAdapter:
    def test_parses_tixr_events(self) -> None:
        events = _parse_fixture(GetDownAdapter(), "getdown.html")
        assert events, "fixture should yield events"
        for e in events:
            assert classify_provider(e.ticket_url) == "tixr", (
                f"{e.headliner!r} link is not Tixr: {e.ticket_url}"
            )
        assert all(e.venue == "The Get Down" for e in events)
        assert all(e.source == "the_get_down" for e in events)
        assert all(e.event_date is not None for e in events)

    def test_doors_time_parsed(self) -> None:
        events = _parse_fixture(GetDownAdapter(), "getdown.html")
        # Fixture events list "DOORS: 8:00 pm" in their text.
        assert any(e.doors_time is not None for e in events)

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(GetDownAdapter(), "getdown.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))


class TestShowdownAdapter:
    def test_parses_events_with_times(self) -> None:
        events = _parse_fixture(ShowdownAdapter(), "showdown.html")
        assert events, "fixture should yield events"
        assert all(e.venue == "The Showdown" for e in events)
        assert all(e.source == "showdown" for e in events)
        assert all(e.event_date is not None for e in events)
        # Both doors and show time should be parsed.
        assert all(e.doors_time is not None for e in events)
        assert all(e.show_time is not None for e in events)

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(ShowdownAdapter(), "showdown.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))

    def test_first_event_fields(self) -> None:
        events = _parse_fixture(ShowdownAdapter(), "showdown.html")
        e = events[0]
        assert e.event_date == date(2026, 6, 21)
        assert e.show_time == dt_time(20, 0)
        assert e.doors_time == dt_time(19, 0)


class TestNovaPdxAdapter:
    def test_parses_tixr_events(self) -> None:
        events = _parse_fixture(NovaPdxAdapter(), "novapdx.html")
        assert events, "fixture should yield events"
        for e in events:
            assert classify_provider(e.ticket_url) == "tixr", (
                f"{e.headliner!r} link is not Tixr: {e.ticket_url}"
            )
        assert all(e.venue == "Nova PDX" for e in events)
        assert all(e.source == "nova_pdx" for e in events)
        assert all(e.event_date is not None for e in events)

    def test_source_ids_unique(self) -> None:
        events = _parse_fixture(NovaPdxAdapter(), "novapdx.html")
        ids = [e.source_id for e in events]
        assert len(ids) == len(set(ids))

    def test_first_event_fields(self) -> None:
        events = _parse_fixture(NovaPdxAdapter(), "novapdx.html")
        e = next(ev for ev in events if ev.headliner == "House Wednesday")
        assert e.event_date == date(2026, 6, 24)
        assert e.show_time is None
        assert e.ticket_url == "https://tixr.com/e/189938"
        assert e.source_id == "189938"
