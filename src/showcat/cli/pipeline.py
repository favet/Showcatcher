"""End-to-end ingest + score driver (live data).

Runs the full chain that turns your Last.fm history and Portland events into
scored, playlist-ready data:

    backfill -> [mbid resolve] -> events -> resolve matches -> tags -> score

Stages still couple only through the database; this is the conductor that runs
them in order. Tags are fetched only for matched artists (after resolve), and
the backfill can be bounded to recent history, so a live run stays fast.

The playlist write itself is separate (opener.cli.playlist) because it needs
the one-time Spotify OAuth consent.
"""
import sys
import time
from datetime import UTC, datetime, timedelta

from showcat.adapters.sources.ticketmaster.adapter import TicketmasterAdapter
from showcat.core import config as _config  # noqa: F401  (loads .env on import)
from showcat.core.base import BaseStage
from showcat.core.database import RunLedger
from showcat.ingest.events.snapshot import EventSnapshotStage
from showcat.ingest.history.backfill import HistoryBackfillStage
from showcat.ingest.history.mbid_resolve import MbidResolveStage
from showcat.ingest.history.tag_ingest import ArtistTagStage
from showcat.resolve.stage import ResolveStage
from showcat.score.stage import ScoreStage


class PipelineError(RuntimeError):
    """Raised when a stage in the pipeline fails (so the run stops loudly)."""


def _run_stage(stage: BaseStage, **kwargs: object) -> int:
    """Run a stage and stop the pipeline if it failed (failure routes to dead_letter)."""
    record: RunLedger = stage.run(**kwargs)
    if record.status != "completed":
        raise PipelineError(
            f"Stage {stage.stage_name} failed: {record.error_message}"
        )
    return record.records_processed or 0


def run_pipeline(
    backfill_days: int | None = 365,
    resolve_mbids: bool = False,
    scoring_version: str = "discovery-v1",
) -> None:
    """Run ingest + score end to end.

    Args:
        backfill_days: only pull scrobbles from the last N days (None = full
            history). Recent history is what decayed affinity weights anyway.
        resolve_mbids: also run MBID resolution (one Last.fm call per unresolved
            artist — slow over a large library; name matching works without it).
        scoring_version: scoring config to persist (default the discovery tilt).
    """
    since_ts: int | None = None
    if backfill_days is not None:
        since_ts = int((datetime.now(UTC) - timedelta(days=backfill_days)).timestamp())

    steps: list[tuple[str, int]] = []
    total = 6 if resolve_mbids else 5

    print(f"[1/{total}] Backfilling Last.fm history...")
    backfill_kwargs = {"since_ts": since_ts} if since_ts else {}
    steps.append(("backfill scrobbles", _run_stage(HistoryBackfillStage(), **backfill_kwargs)))

    if resolve_mbids:
        print("[2/6] Resolving artist MBIDs...")
        steps.append(("mbids resolved", _run_stage(MbidResolveStage())))

    from showcat.adapters.sources.custom import ALL_CUSTOM_ADAPTERS

    n = len(steps) + 1
    print(f"[{n}/{total}] Ingesting Ticketmaster events...")
    
    total_event_changes = 0
    try:
        total_event_changes += _run_stage(EventSnapshotStage(TicketmasterAdapter()))
    except Exception as e:
        print(f"  [warn] Ticketmaster adapter failed: {e}")
        
    print(f"[{n}/{total}] Ingesting Custom Venue events...")
    for AdapterClass in ALL_CUSTOM_ADAPTERS:
        try:
            total_event_changes += _run_stage(EventSnapshotStage(AdapterClass()))
        except Exception as e:
            print(f"  [warn] {AdapterClass.__name__} failed: {e}")
            
    steps.append(("event changes", total_event_changes))

    print(f"[{n + 1}/{total}] Resolving event artists to taste...")
    steps.append(("artist matches", _run_stage(ResolveStage())))

    print(f"[{n + 2}/{total}] Fetching tags for matched artists...")
    steps.append(("tag rows", _run_stage(ArtistTagStage(matched_only=True))))

    print(f"[{n + 3}/{total}] Scoring shows ({scoring_version})...")
    steps.append(("scored shows", _run_stage(ScoreStage(scoring_version=scoring_version))))

    print("\nDone. Summary:")
    for label, count in steps:
        print(f"  {label:<22} {count}")


if __name__ == "__main__":
    days: int | None = 365
    if len(sys.argv) > 1:
        days = None if sys.argv[1] == "full" else int(sys.argv[1])
    start = time.monotonic()
    run_pipeline(backfill_days=days)
    print(f"\nElapsed: {time.monotonic() - start:.1f}s")
