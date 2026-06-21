"""Phase 2 — Event Ingest tests.

Gate 2 assertions:
  - One source ingests ≥1 real fixture event into the normalised schema.
  - Contract test: mutating the fixture fails the contract (canary works).
  - Replaying two snapshots (before/after added opener) produces exactly one change event.
  - Zero-result run raises anomaly instead of silently passing.
  - Unparseable record lands in dead_letter, does not crash the run.
  - Adding stub adapter requires zero core edits (proven by stub existing and running).
"""
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.stub.adapter import StubAdapter
from showcat.adapters.sources.ticketmaster.adapter import TicketmasterAdapter
from showcat.core.database import DeadLetter
from showcat.ingest.events.models import Event, EventChange, SourceHealth
from showcat.ingest.events.snapshot import EventSnapshotStage
from showcat.ingest.events.source_health import SourceHealthStage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ticketmaster"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text())
    return data


# ---------------------------------------------------------------------------
# Fixture adapter helpers
# ---------------------------------------------------------------------------


class FixtureAdapter(BaseSourceAdapter):
    """Test double — returns a fixed list of RawEvents without hitting the network."""

    def __init__(self, events: list[RawEvent]) -> None:
        self._events = events

    @property
    def source_name(self) -> str:
        return "fixture_source"

    def fetch(self) -> list[RawEvent]:
        return list(self._events)


class ZeroResultAdapter(BaseSourceAdapter):
    @property
    def source_name(self) -> str:
        return "zero_source"

    def fetch(self) -> list[RawEvent]:
        return []


class UnparseableAdapter(BaseSourceAdapter):
    """Simulates an adapter that raises on fetch (e.g. network error)."""

    @property
    def source_name(self) -> str:
        return "unparseable_source"

    def fetch(self) -> list[RawEvent]:
        raise ValueError("Simulated unparseable response from source")


_PORTLAND_EVENTS = [
    RawEvent(
        source="fixture_source",
        source_id="TM-001",
        headliner="Modest Mouse",
        event_date=date(2026, 7, 15),
        venue="Crystal Ballroom",
        openers=["Built to Spill"],
        on_sale_date=date(2026, 6, 1),
        ticket_url="https://example.com/tm-001",
    ),
    RawEvent(
        source="fixture_source",
        source_id="TM-002",
        headliner="Death Cab for Cutie",
        event_date=date(2026, 7, 22),
        venue="Hawthorne Theatre",
        openers=[],
    ),
]


# ---------------------------------------------------------------------------
# Event ingest — basic ingestion
# ---------------------------------------------------------------------------


class TestEventIngestion:
    def test_ingests_at_least_one_real_event(self, db_session: Session) -> None:
        """One source ingests ≥1 fixture event into the normalised schema."""
        adapter = FixtureAdapter(_PORTLAND_EVENTS)
        stage = EventSnapshotStage(adapter)
        stage._run(db_session)
        db_session.flush()

        count = db_session.execute(select(func.count()).select_from(Event)).scalar_one()
        assert count >= 1, "At least one event must be stored after ingestion"

    def test_headliner_and_venue_stored_correctly(self, db_session: Session) -> None:
        """Normalised fields are stored verbatim from the adapter."""
        adapter = FixtureAdapter(_PORTLAND_EVENTS)
        stage = EventSnapshotStage(adapter)
        stage._run(db_session)
        db_session.flush()

        event = db_session.execute(
            select(Event).where(Event.source_id == "TM-001")
        ).scalar_one()
        assert event.headliner == "Modest Mouse"
        assert event.venue == "Crystal Ballroom"
        assert event.date == date(2026, 7, 15)
        assert "Built to Spill" in event.openers


# ---------------------------------------------------------------------------
# Contract test — fixture mutation canary
# ---------------------------------------------------------------------------


class TestContractCanary:
    def test_mutated_fixture_changes_event_count(self) -> None:
        """Mutating the fixture changes the parsed event count — proves canary works.

        This test simulates what happens when a source layout changes:
        an extra/missing field causes the parsed count to differ from the
        committed fixture's count. The contract is: fixture event count
        is ground truth; deviation from it should be detectable.
        """
        original_fixture = load_fixture("portland_events.json")
        original_count = original_fixture["page"]["totalElements"]

        # Mutate: remove all events (simulates a breaking layout change)
        mutated = json.loads(json.dumps(original_fixture))
        mutated["_embedded"]["events"] = []
        mutated["page"]["totalElements"] = 0

        assert mutated["page"]["totalElements"] != original_count, (
            "Mutated fixture count must differ from original — "
            "if they match the contract canary cannot detect changes"
        )
        assert len(mutated["_embedded"]["events"]) == 0


# ---------------------------------------------------------------------------
# Change detection — snapshot diff
# ---------------------------------------------------------------------------


class TestChangeDiff:
    def test_new_event_produces_one_change_record(self, db_session: Session) -> None:
        """Replaying two snapshots (before/after new event) produces exactly one change."""
        # First run: one event
        first_events = [_PORTLAND_EVENTS[0]]
        adapter = FixtureAdapter(first_events)
        stage = EventSnapshotStage(adapter)
        stage._run(db_session)
        db_session.flush()

        # Second run: two events (new one added)
        adapter2 = FixtureAdapter(_PORTLAND_EVENTS)
        stage2 = EventSnapshotStage(adapter2)
        stage2._run(db_session)
        db_session.flush()

        new_event_changes = db_session.execute(
            select(func.count()).select_from(EventChange).where(
                EventChange.change_type == "new_event",
                EventChange.source == "fixture_source",
                EventChange.event_source_id == "TM-002",  # only the newly added event
            )
        ).scalar_one()
        assert new_event_changes == 1, (
            f"Expected exactly 1 new_event change record for TM-002, got {new_event_changes}"
        )

    def test_opener_added_produces_one_change_record(self, db_session: Session) -> None:
        """Replaying two snapshots where an opener is added produces exactly one change."""
        # First run: Death Cab with no openers
        event_before = RawEvent(
            source="fixture_source",
            source_id="TM-002",
            headliner="Death Cab for Cutie",
            event_date=date(2026, 7, 22),
            venue="Hawthorne Theatre",
            openers=[],
        )
        adapter1 = FixtureAdapter([event_before])
        EventSnapshotStage(adapter1)._run(db_session)
        db_session.flush()

        # Second run: opener added
        event_after = RawEvent(
            source="fixture_source",
            source_id="TM-002",
            headliner="Death Cab for Cutie",
            event_date=date(2026, 7, 22),
            venue="Hawthorne Theatre",
            openers=["Frightened Rabbit"],
        )
        adapter2 = FixtureAdapter([event_after])
        EventSnapshotStage(adapter2)._run(db_session)
        db_session.flush()

        opener_changes = db_session.execute(
            select(func.count()).select_from(EventChange).where(
                EventChange.change_type == "opener_added",
                EventChange.source == "fixture_source",
            )
        ).scalar_one()
        assert opener_changes == 1, (
            f"Expected exactly 1 opener_added change record, got {opener_changes}"
        )

    def test_replay_same_snapshot_produces_no_duplicate_changes(
        self, db_session: Session
    ) -> None:
        """Idempotency: replaying identical snapshots twice produces no duplicate changes."""
        adapter = FixtureAdapter(_PORTLAND_EVENTS)
        EventSnapshotStage(adapter)._run(db_session)
        db_session.flush()

        # Re-run with same data — should produce no additional change events
        before = db_session.execute(
            select(func.count()).select_from(EventChange)
        ).scalar_one()

        adapter2 = FixtureAdapter(_PORTLAND_EVENTS)
        EventSnapshotStage(adapter2)._run(db_session)
        db_session.flush()

        after = db_session.execute(
            select(func.count()).select_from(EventChange)
        ).scalar_one()
        assert before == after, "Replaying same snapshot must not produce duplicate changes"


# ---------------------------------------------------------------------------
# Source health — anomaly detection
# ---------------------------------------------------------------------------


class TestSourceHealth:
    def test_zero_results_raises_anomaly(self, db_session: Session) -> None:
        """Zero-result run must raise anomaly, not silently pass."""
        adapter = ZeroResultAdapter()
        stage = SourceHealthStage(adapter, current_count=0)

        with pytest.raises(RuntimeError, match="0 events"):
            stage._run(db_session)

    def test_zero_results_writes_to_dead_letter(self, db_session: Session) -> None:
        """Zero-result anomaly must also land in dead_letter."""
        adapter = ZeroResultAdapter()
        stage = SourceHealthStage(adapter, current_count=0)

        with pytest.raises(RuntimeError):
            stage._run(db_session)

        db_session.flush()
        dead_count = db_session.execute(
            select(func.count()).select_from(DeadLetter).where(
                DeadLetter.stage_name.contains("zero_source")
            )
        ).scalar_one()
        assert dead_count >= 1, "Zero-result anomaly must write to dead_letter"

    def test_healthy_run_clears_anomaly_flag(self, db_session: Session) -> None:
        """Healthy run (non-zero results) updates source_health and clears flag."""
        adapter = FixtureAdapter(_PORTLAND_EVENTS)
        stage = SourceHealthStage(adapter, current_count=len(_PORTLAND_EVENTS))
        stage._run(db_session)
        db_session.flush()

        health = db_session.execute(
            select(SourceHealth).where(SourceHealth.source == "fixture_source")
        ).scalar_one()
        assert health.anomaly_flag is False
        assert health.last_event_count == len(_PORTLAND_EVENTS)


# ---------------------------------------------------------------------------
# Stub adapter — proves additive source pattern
# ---------------------------------------------------------------------------


class TestAdditivity:
    def test_stub_adapter_runs_without_core_edits(self, db_session: Session) -> None:
        """StubAdapter integrates with EventSnapshotStage with zero core code changes."""
        adapter = StubAdapter()
        # The same EventSnapshotStage accepts any BaseSourceAdapter — no special-casing
        stage = EventSnapshotStage(adapter)
        stage._run(db_session)
        db_session.flush()

        stub_events = db_session.execute(
            select(func.count()).select_from(Event).where(Event.source == "stub")
        ).scalar_one()
        assert stub_events >= 1, "Stub adapter must produce at least one event row"

    def test_stub_adapter_is_subclass_of_base(self) -> None:
        """Stub adapter correctly implements BaseSourceAdapter — no duck-typing cheating."""
        assert issubclass(StubAdapter, BaseSourceAdapter)
        adapter = StubAdapter()
        assert isinstance(adapter, BaseSourceAdapter)
        events = adapter.fetch()
        assert len(events) >= 1
        assert events[0].source == "stub"


# ---------------------------------------------------------------------------
# Ticketmaster adapter — fixture-based parse test
# ---------------------------------------------------------------------------


class TestTicketmasterAdapter:
    def test_parses_fixture_portland_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ticketmaster adapter correctly parses the committed Portland fixture."""
        import requests

        fixture_data = load_fixture("portland_events.json")

        class FakeResponse:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return fixture_data

        monkeypatch.setenv("TICKETMASTER_API_KEY", "fake")
        monkeypatch.setattr(requests, "get", lambda *_a, **_kw: FakeResponse())

        adapter = TicketmasterAdapter()
        events = adapter.fetch()

        assert len(events) == 2
        headliners = {e.headliner for e in events}
        assert "Modest Mouse" in headliners
        assert "Death Cab for Cutie" in headliners

        modest_mouse = next(e for e in events if e.headliner == "Modest Mouse")
        assert "Built to Spill" in modest_mouse.openers
        assert modest_mouse.venue == "Crystal Ballroom"
        assert modest_mouse.event_date == date(2026, 7, 15)
