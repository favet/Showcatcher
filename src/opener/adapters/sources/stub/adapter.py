"""Stub second source adapter — proves the additive adapter pattern.

This adapter exists solely to demonstrate that adding a new event source
requires ONLY:
  1. A new adapter subclass (this file)
  2. A config entry pointing to it

No edits to core/, ingest/, or any pipeline code.

In Phase 6, real adapters for additional Portland venues will replace this stub.
"""
from datetime import date

from opener.adapters.sources.base import BaseSourceAdapter, RawEvent


class StubAdapter(BaseSourceAdapter):
    """Minimal second source adapter — returns hardcoded fixture data."""

    @property
    def source_name(self) -> str:
        return "stub"

    def fetch(self) -> list[RawEvent]:
        """Return a single hardcoded event — enough to prove the pattern works."""
        return [
            RawEvent(
                source=self.source_name,
                source_id="stub-001",
                headliner="Test Band",
                event_date=date(2026, 8, 1),
                venue="Stub Venue",
                openers=["Opening Act"],
                on_sale_date=date(2026, 7, 1),
                ticket_url="https://example.com/stub-001",
            )
        ]
