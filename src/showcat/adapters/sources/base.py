"""Source adapter base interface.

Every event source adapter (Ticketmaster, venue-site scrapers, etc.)
implements BaseSourceAdapter. All source-specific parsing lives in the
concrete adapter — core pipeline code only sees RawEvent objects.

Adding a new source = new adapter subclass + config entry. Zero core edits.
"""
import abc
from dataclasses import dataclass, field
from datetime import date, time


@dataclass
class RawEvent:
    """Normalised event as returned by any source adapter.

    Fields are the non-negotiable schema from ARCHITECTURE.md.
    """

    source: str
    source_id: str
    headliner: str
    event_date: date
    venue: str
    openers: list[str] = field(default_factory=list)
    doors_time: time | None = None
    show_time: time | None = None
    on_sale_date: date | None = None
    ticket_url: str | None = None


class BaseSourceAdapter(abc.ABC):
    """Narrow interface all event source adapters must implement."""

    @property
    @abc.abstractmethod
    def source_name(self) -> str:
        """Unique source identifier, e.g. 'ticketmaster' or 'stub'."""

    @abc.abstractmethod
    def fetch(self) -> list[RawEvent]:
        """Fetch current upcoming events from the source.

        Returns:
            List of normalised RawEvent objects.
            May return an empty list — empty lists are handled by
            SourceHealthStage (raises anomaly; never silently passes).

        Raises:
            Should raise on connection failures so dead-letter routing
            in SourceHealthStage can capture context.
        """
