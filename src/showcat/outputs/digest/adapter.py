"""Ticket digest output adapter.

Renders matched, scored upcoming shows for artists you already know — each
entry carries its ticket_url, on_sale_date, and full score breakdown (no
black box). Ordering is deterministic (score desc, then date, then source
id) so the rendered digest is a stable golden artifact.
"""
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist
from showcat.outputs.base import BaseOutputAdapter
from showcat.resolve.models import EventMatch
from showcat.score.models import EventScore
from showcat.score.scorer import SCORING_VERSION


@dataclass(frozen=True)
class DigestEntry:
    """One digest row: an upcoming show with its buy info and score breakdown."""

    headliner: str
    venue: str
    date: str  # ISO date
    source: str
    source_id: str
    score_total: float
    score_terms: dict[str, float]
    matched_artists: list[str]
    ticket_url: str | None = None
    on_sale_date: str | None = None  # ISO date or None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Digest:
    """The full digest artifact — an ordered list of entries."""

    scoring_version: str
    entries: list[DigestEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scoring_version": self.scoring_version,
            "entries": [e.to_dict() for e in self.entries],
        }


class DigestOutputAdapter(BaseOutputAdapter):
    """Builds the ticket digest from matched + scored events in Postgres."""

    @property
    def output_name(self) -> str:
        return "digest"

    def build(self, session: Session) -> Digest:
        rows = session.execute(
            select(Event, EventScore)
            .join(EventScore, EventScore.event_id == Event.id)
            .where(EventScore.scoring_version == SCORING_VERSION)
        ).all()

        entries: list[DigestEntry] = []
        for event, score in rows:
            matched_artists = (
                session.execute(
                    select(Artist.raw_name)
                    .join(EventMatch, EventMatch.artist_id == Artist.id)
                    .where(
                        EventMatch.event_id == event.id,
                        EventMatch.status == "matched",
                    )
                    .order_by(Artist.raw_name)
                )
                .scalars()
                .all()
            )
            entries.append(
                DigestEntry(
                    headliner=event.headliner,
                    venue=event.venue,
                    date=event.date.isoformat(),
                    source=event.source,
                    source_id=event.source_id,
                    score_total=score.score_total,
                    score_terms={
                        "taste": score.taste_score,
                        "adjacency": score.adjacency_score,
                        "discovery": score.discovery_score,
                        "recency": score.recency_score,
                        "distance": score.distance_score,
                    },
                    matched_artists=list(matched_artists),
                    ticket_url=event.ticket_url,
                    on_sale_date=event.on_sale_date.isoformat() if event.on_sale_date else None,
                )
            )

        # Deterministic ordering: highest score first, then soonest date, then id.
        entries.sort(key=lambda e: (-e.score_total, e.date, e.source_id))
        return Digest(scoring_version=SCORING_VERSION, entries=entries)

    def render_text(self, digest: Digest) -> str:
        """Human-readable digest. Deterministic given a deterministic Digest."""
        lines = [
            f"Ticket Digest — {len(digest.entries)} show(s) "
            f"[scoring: {digest.scoring_version}]",
            "=" * 60,
        ]
        for e in digest.entries:
            on_sale = e.on_sale_date or "on sale now / TBA"
            lines.append(f"{e.headliner} @ {e.venue} — {e.date}")
            lines.append(f"  score {e.score_total:.4f}  terms={e.score_terms}")
            lines.append(f"  on-sale: {on_sale}")
            lines.append(f"  tickets: {e.ticket_url or 'n/a'}")
            lines.append("")
        return "\n".join(lines)

    def render_ics(self, digest: Digest) -> str:
        """Minimal RFC-5545 calendar of the shows (optional companion artifact)."""
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Opener//Digest//EN"]
        for e in digest.entries:
            stamp = e.date.replace("-", "")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{e.source}-{e.source_id}@opener",
                f"DTSTART;VALUE=DATE:{stamp}",
                f"SUMMARY:{e.headliner} @ {e.venue}",
                f"DESCRIPTION:Tickets {e.ticket_url or 'n/a'} (on-sale {e.on_sale_date or 'TBA'})",
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        return "\n".join(lines)
