"""Output adapter base interface.

Every deliverable (ticket digest, Spotify playlist) is produced behind an
output adapter that reads already-scored data from Postgres and renders an
artifact. Keeping outputs behind an adapter is what lets the engine grow a
new deliverable additively, and lets the Spotify bridge be swapped for an
export-file fallback without touching the pipeline (DECISIONS D6/D7).
"""
import abc
from typing import Any

from sqlalchemy.orm import Session


class BaseOutputAdapter(abc.ABC):
    """Narrow interface all output adapters implement."""

    @property
    @abc.abstractmethod
    def output_name(self) -> str:
        """Unique output identifier, e.g. 'digest' or 'playlist'."""

    @abc.abstractmethod
    def build(self, session: Session) -> Any:
        """Read scored data from the DB and return a structured artifact.

        Rendering to a concrete format (text, .ics, JSON) is left to the
        concrete adapter; `build` produces the inspectable intermediate so
        outputs are testable as data, not just as rendered strings.
        """
