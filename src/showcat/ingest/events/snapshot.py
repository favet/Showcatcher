"""EventSnapshotStage — stores raw fetches, diffs snapshots, records changes.

Change detection:
- new_event: a source_id appears that was not in the previous snapshot
- opener_added: an opener name appears in the current event that wasn't before

Idempotency: re-running with identical data produces no new EventChange rows
(the unique constraint on event_changes prevents duplicates).
"""
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.tickets.providers import classify_provider
from showcat.core.base import BaseStage
from showcat.adapters.sources.title_parser import (
    is_non_show,
    normalize_title,
    split_multi_artist_comma,
    split_multi_artist_plus,
)
from showcat.ingest.events.models import Event, EventChange, EventSnapshot

logger = logging.getLogger(__name__)


def _raw_event_to_dict(event: RawEvent) -> dict[str, Any]:
    return {
        "source": event.source,
        "source_id": event.source_id,
        "headliner": event.headliner,
        "openers": event.openers,
        "date": event.event_date.isoformat(),
        "doors_time": event.doors_time.isoformat() if event.doors_time else None,
        "show_time": event.show_time.isoformat() if event.show_time else None,
        "venue": event.venue,
        "on_sale_date": event.on_sale_date.isoformat() if event.on_sale_date else None,
        "ticket_url": event.ticket_url,
        "price": event.price,
        "image_url": event.image_url,
        "description": event.description,
    }


class EventSnapshotStage(BaseStage):
    """Snapshot + diff change detection for one event source."""

    def __init__(self, adapter: BaseSourceAdapter) -> None:
        self._adapter = adapter

    @property
    def stage_name(self) -> str:
        return f"ingest/events/snapshot/{self._adapter.source_name}"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        source = self._adapter.source_name
        now = datetime.now(UTC)

        # --- 1. Fetch current events from the adapter ---
        current_events = self._adapter.fetch()

        # --- 2. Store snapshot ---
        raw_content = json.dumps([_raw_event_to_dict(e) for e in current_events])
        snapshot = EventSnapshot(
            source=source,
            captured_at=now,
            raw_content=raw_content,
            event_count=len(current_events),
        )
        session.add(snapshot)
        session.flush()

        # --- 3. Load previous snapshot for diff ---
        prev_snapshot = (
            session.query(EventSnapshot)
            .filter(EventSnapshot.source == source)
            .order_by(EventSnapshot.captured_at.desc())
            .offset(1)  # skip the one we just inserted
            .first()
        )

        prev_events: dict[str, dict[str, Any]] = {}
        if prev_snapshot:
            for ev in json.loads(prev_snapshot.raw_content):
                prev_events[ev["source_id"]] = ev

        # --- 4. Detect changes + upsert events ---
        changes_recorded = 0

        for raw_event in current_events:
            # Normalize: entities, whitespace, status prefix, age/tour suffixes, w/ opener
            clean_headliner, w_openers, _status = normalize_title(
                raw_event.headliner,
                existing_openers=list(raw_event.openers),
            )
            # Split multi-artist bills packed into the title
            clean_headliner, plus_openers = split_multi_artist_plus(
                clean_headliner, existing_openers=w_openers
            )
            clean_headliner, all_openers = split_multi_artist_comma(
                clean_headliner, existing_openers=plus_openers
            )

            if is_non_show(clean_headliner):
                continue

            ticket_provider = classify_provider(raw_event.ticket_url)
            # Upsert the event row
            stmt = (
                pg_insert(Event)
                .values(
                    source=raw_event.source,
                    source_id=raw_event.source_id,
                    headliner=clean_headliner,
                    openers=all_openers,
                    date=raw_event.event_date,
                    doors_time=raw_event.doors_time,
                    show_time=raw_event.show_time,
                    venue=raw_event.venue,
                    on_sale_date=raw_event.on_sale_date,
                    ticket_url=raw_event.ticket_url,
                    ticket_provider=ticket_provider,
                    price=raw_event.price,
                    image_url=raw_event.image_url,
                    sold_out=raw_event.sold_out,
                    description=raw_event.description,
                    first_seen=now,
                    last_seen=now,
                )
                .on_conflict_do_update(
                    constraint="uq_events_source_id",
                    set_={
                        "last_seen": now,
                        "headliner": clean_headliner,
                        "openers": all_openers,
                        "doors_time": raw_event.doors_time,
                        "show_time": raw_event.show_time,
                        "ticket_url": raw_event.ticket_url,
                        "ticket_provider": ticket_provider,
                        # Only overwrite price/image/description if the new scrape has them
                        # (prevents erasure when the source stops returning them).
                        **(({"price": raw_event.price}) if raw_event.price else {}),
                        **(({"image_url": raw_event.image_url}) if raw_event.image_url else {}),
                        **(({"description": raw_event.description}) if raw_event.description else {}),
                        "sold_out": raw_event.sold_out,
                    },
                )
            )
            session.execute(stmt)

            prev = prev_events.get(raw_event.source_id)
            if prev is None:
                # NEW EVENT
                change = EventChange(
                    source=source,
                    event_source_id=raw_event.source_id,
                    change_type="new_event",
                    change_detail={
                            "headliner": clean_headliner,
                            "date": raw_event.event_date.isoformat(),
                        },
                    detected_at=now,
                )
                result = session.execute(
                    pg_insert(EventChange)
                    .values(
                        source=change.source,
                        event_source_id=change.event_source_id,
                        change_type=change.change_type,
                        change_detail=change.change_detail,
                        detected_at=change.detected_at,
                    )
                    .on_conflict_do_nothing(constraint="uq_event_changes_unique")
                )
                if isinstance(result, CursorResult) and result.rowcount:
                    changes_recorded += 1
                logger.info(
                    "New event detected",
                    extra={"source": source, "source_id": raw_event.source_id,
                           "headliner": raw_event.headliner},
                )
            else:
                # Check for added openers
                prev_openers = set(prev.get("openers", []))
                curr_openers = set(all_openers)
                new_openers = curr_openers - prev_openers
                for opener in new_openers:
                    result = session.execute(
                        pg_insert(EventChange)
                        .values(
                            source=source,
                            event_source_id=raw_event.source_id,
                            change_type="opener_added",
                            change_detail={"opener": opener},
                            detected_at=now,
                        )
                        .on_conflict_do_nothing(constraint="uq_event_changes_unique")
                    )
                    if isinstance(result, CursorResult) and result.rowcount:
                        changes_recorded += 1
                    logger.info(
                        "Opener added to event",
                        extra={"source": source, "source_id": raw_event.source_id,
                               "opener": opener},
                    )

        logger.info(
            "Snapshot stage complete",
            extra={"source": source, "events": len(current_events), "changes": changes_recorded},
        )
        return changes_recorded
