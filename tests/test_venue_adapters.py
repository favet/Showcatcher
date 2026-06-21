"""Phase 8.3 — venue-direct scraper tests.

Each venue adapter parses its committed fixture into RawEvents whose ticket_url
points at the venue's real (non-Ticketmaster) ticketer. Runs offline.
"""
from datetime import date
from datetime import time as dt_time
from pathlib import Path

from showcat.adapters.sources.custom.aladdin import AladdinAdapter
from showcat.adapters.tickets.providers import classify_provider

FIXTURES = Path(__file__).parent / "fixtures" / "venues"


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
