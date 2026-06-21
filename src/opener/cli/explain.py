"""explain — answer "why did show X score Y?".

Prints the persisted, decomposed score breakdown for an event: each named
term's contribution, the total, the scoring version, and the matched artists
that drove it. This is the "never a black box" affordance for scoring; it
reads only persisted data, so the explanation is exactly what the ranking used.
"""
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from opener.core import database
from opener.ingest.events.models import Event
from opener.ingest.history.models import Artist
from opener.resolve.models import EventMatch
from opener.score.models import EventScore


def explain_show(session: Session, event_id: int) -> str:
    """Return a human-readable explanation of an event's score(s)."""
    event = session.execute(
        select(Event).where(Event.id == event_id)
    ).scalar_one_or_none()
    if event is None:
        return f"No event with id {event_id}."

    scores = (
        session.execute(
            select(EventScore)
            .where(EventScore.event_id == event_id)
            .order_by(EventScore.scoring_version)
        )
        .scalars()
        .all()
    )
    matched_artists = (
        session.execute(
            select(Artist.raw_name, EventMatch.match_type, EventMatch.confidence)
            .join(EventMatch, EventMatch.artist_id == Artist.id)
            .where(EventMatch.event_id == event_id, EventMatch.status == "matched")
            .order_by(Artist.raw_name)
        )
        .all()
    )

    lines = [
        f"Why show #{event_id}: {event.headliner} @ {event.venue} ({event.date.isoformat()})",
        "-" * 60,
    ]
    if matched_artists:
        lines.append("Matched taste artists:")
        for name, match_type, confidence in matched_artists:
            lines.append(f"  - {name}  [{match_type}, confidence {confidence:.3f}]")
    else:
        lines.append("Matched taste artists: (none)")

    if not scores:
        lines.append("")
        lines.append("No score computed yet for this show.")
        return "\n".join(lines)

    for score in scores:
        terms = {
            "taste": score.taste_score,
            "adjacency": score.adjacency_score,
            "discovery": score.discovery_score,
            "recency": score.recency_score,
            "distance": score.distance_score,
        }
        lines.append("")
        lines.append(f"Scoring version: {score.scoring_version}")
        for term, value in terms.items():
            lines.append(f"  {term:<10} {value:>10.4f}")
        lines.append(f"  {'TOTAL':<10} {score.score_total:>10.4f}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m opener.cli.explain <event_id>", file=sys.stderr)
        return 2
    try:
        event_id = int(argv[0])
    except ValueError:
        print(f"event_id must be an integer, got {argv[0]!r}", file=sys.stderr)
        return 2
    with database.get_db_session() as session:
        print(explain_show(session, event_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
