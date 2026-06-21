"""SourceHealthStage — anomaly detection for event sources.

Rules:
  - Zero results ALWAYS raises an anomaly (broken source, not empty calendar).
  - Count drops >50% vs 7-run trailing average also raises anomaly.
  - Anomalies are written to source_health AND dead_letter.
  - Healthy runs update last_success_at and clear the anomaly flag.
"""
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from opener.adapters.sources.base import BaseSourceAdapter
from opener.core.base import BaseStage
from opener.core.database import DeadLetter
from opener.ingest.events.models import SourceHealth

logger = logging.getLogger(__name__)

TRAILING_WINDOW = 7  # number of recent runs to average
DROP_THRESHOLD = 0.5  # flag if current count < (1 - threshold) * avg


class SourceHealthStage(BaseStage):
    """Monitor source result counts and raise anomalies for zero/low results."""

    def __init__(self, adapter: BaseSourceAdapter, current_count: int) -> None:
        self._adapter = adapter
        self._current_count = current_count

    @property
    def stage_name(self) -> str:
        return f"ingest/events/health/{self._adapter.source_name}"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        source = self._adapter.source_name
        now = datetime.now(UTC)
        count = self._current_count

        # Load existing health record
        health = session.execute(
            select(SourceHealth).where(SourceHealth.source == source)
        ).scalar_one_or_none()

        trailing: list[int] = []
        if health and health.trailing_counts:
            trailing = list(health.trailing_counts)

        anomaly = False
        anomaly_reason: str | None = None

        # Rule 1: zero results is always an anomaly
        if count == 0:
            anomaly = True
            anomaly_reason = (
                f"Source '{source}' returned 0 events — likely broken, not an empty calendar."
            )
            logger.error("Source health anomaly: zero results", extra={"source": source})

        # Rule 2: large drop vs trailing average
        elif len(trailing) >= 3:
            avg = sum(trailing[-TRAILING_WINDOW:]) / len(trailing[-TRAILING_WINDOW:])
            if avg > 0 and count < avg * (1 - DROP_THRESHOLD):
                anomaly = True
                anomaly_reason = (
                    f"Source '{source}' returned {count} events vs trailing avg {avg:.1f} "
                    f"(>{DROP_THRESHOLD*100:.0f}% drop)."
                )
                logger.warning(
                    "Source health anomaly: large count drop",
                    extra={"source": source, "count": count, "trailing_avg": avg},
                )

        if anomaly and anomaly_reason:
            # Write to dead_letter for visibility
            session.add(
                DeadLetter(
                    stage_name=self.stage_name,
                    raw_content=json.dumps(
                        {"source": source, "count": count, "trailing": trailing}
                    ),
                    error_message=anomaly_reason,
                    occurred_at=now,
                )
            )

        # Update trailing counts (keep last TRAILING_WINDOW)
        trailing.append(count)
        trailing = trailing[-TRAILING_WINDOW:]

        # Upsert source_health row
        upsert_values: dict[str, Any] = {
            "source": source,
            "last_event_count": count,
            "trailing_counts": trailing,
            "anomaly_flag": anomaly,
            "anomaly_reason": anomaly_reason,
        }
        if not anomaly:
            upsert_values["last_success_at"] = now

        session.execute(
            pg_insert(SourceHealth)
            .values(**upsert_values)
            .on_conflict_do_update(
                index_elements=["source"],
                set_={k: v for k, v in upsert_values.items() if k != "source"},
            )
        )

        if anomaly:
            raise RuntimeError(anomaly_reason)

        logger.info(
            "Source health OK", extra={"source": source, "count": count}
        )
        return 1
