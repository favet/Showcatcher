"""Phase 8.1 — ticket-provider classification and link preference."""
import datetime as dt
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.tickets.providers import (
    best_link,
    classify_provider,
    provider_label,
    rank_of,
)
from showcat.ingest.events.models import Event
from showcat.ingest.events.snapshot import EventSnapshotStage


class TestClassifyProvider:
    def test_ticketmaster_domains(self) -> None:
        assert classify_provider("https://www.ticketmaster.com/event/abc") == "ticketmaster"
        assert classify_provider("https://concerts.livenation.com/x") == "ticketmaster"

    def test_named_non_tm_ticketers(self) -> None:
        assert classify_provider("https://www.etix.com/ticket/p/123/show") == "etix"
        assert classify_provider("https://dice.fm/event/abc") == "dice"
        assert classify_provider("https://www.eventbrite.com/e/123") == "eventbrite"
        assert classify_provider("https://www.ticketweb.com/event/9") == "ticketweb"

    def test_unknown_real_host_is_venue(self) -> None:
        assert classify_provider("https://crystalballroompdx.com/events/foo") == "venue"
        assert classify_provider("https://kentonclub.com/") == "venue"

    def test_empty_is_none(self) -> None:
        assert classify_provider(None) == "none"
        assert classify_provider("") == "none"
        assert classify_provider("not a url") == "none"


class TestPreferenceRanking:
    def test_non_tm_ticketer_beats_ticketmaster(self) -> None:
        assert rank_of("etix") > rank_of("ticketmaster")
        assert rank_of("dice") > rank_of("ticketmaster")

    def test_venue_beats_ticketmaster(self) -> None:
        assert rank_of("venue") > rank_of("ticketmaster")

    def test_ticketmaster_beats_unknown_none(self) -> None:
        assert rank_of("ticketmaster") > rank_of("unknown")
        assert rank_of("unknown") > rank_of("none")

    def test_best_link_prefers_etix_over_tm(self) -> None:
        url, provider = best_link(
            ["https://www.ticketmaster.com/event/x", "https://www.etix.com/ticket/p/9/show"]
        )
        assert provider == "etix"
        assert "etix.com" in (url or "")

    def test_best_link_order_independent(self) -> None:
        a = best_link(["https://etix.com/x", "https://ticketmaster.com/y"])
        b = best_link(["https://ticketmaster.com/y", "https://etix.com/x"])
        assert a[1] == b[1] == "etix"

    def test_best_link_falls_back_to_tm_when_only_option(self) -> None:
        url, provider = best_link(["https://www.ticketmaster.com/event/x", None])
        assert provider == "ticketmaster"
        assert url == "https://www.ticketmaster.com/event/x"

    def test_best_link_all_empty(self) -> None:
        assert best_link([None, "", "garbage"]) == (None, "none")


class TestProviderLabel:
    def test_labels(self) -> None:
        assert provider_label("etix") == "Etix"
        assert provider_label("dice") == "Dice"
        assert provider_label("ticketmaster") == "Ticketmaster"
        assert provider_label("venue") == "Venue"
        assert provider_label(None) == "Tickets"


class _StubAdapter(BaseSourceAdapter):
    """Yields fixed RawEvents — exercises snapshot provider persistence."""

    def __init__(self, events: list[RawEvent]) -> None:
        self._events = events

    @property
    def source_name(self) -> str:
        return "stub_provider_src"

    def fetch(self) -> list[RawEvent]:
        return self._events


class TestSnapshotPersistsProvider:
    def test_provider_persisted_on_upsert(self, db_session: Session) -> None:
        raw = RawEvent(
            source="stub_provider_src",
            source_id="SP1",
            headliner="Some Band",
            openers=[],
            event_date=dt.date(2026, 8, 1),
            venue="Crystal Ballroom",
            on_sale_date=None,
            ticket_url="https://www.etix.com/ticket/p/55/show",
        )
        EventSnapshotStage(_StubAdapter([raw]))._run(db_session)
        db_session.flush()

        event = db_session.execute(
            select(Event).where(Event.source_id == "SP1")
        ).scalar_one()
        assert event.ticket_provider == "etix"

    def test_ticketmaster_url_classified(self, db_session: Session) -> None:
        raw = RawEvent(
            source="stub_provider_src",
            source_id="SP2",
            headliner="Another Band",
            openers=[],
            event_date=dt.date(2026, 8, 2),
            venue="Roseland Theater",
            on_sale_date=None,
            ticket_url="https://www.ticketmaster.com/event/zzz",
        )
        EventSnapshotStage(_StubAdapter([raw]))._run(db_session)
        db_session.flush()

        event = db_session.execute(
            select(Event).where(Event.source_id == "SP2")
        ).scalar_one()
        assert event.ticket_provider == "ticketmaster"
        # sanity: created_at-style fields still set
        assert isinstance(event.first_seen, datetime)
