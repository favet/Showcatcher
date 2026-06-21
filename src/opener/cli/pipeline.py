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

from opener.adapters.sources.ticketmaster.adapter import TicketmasterAdapter
from opener.ingest.events.snapshot import EventSnapshotStage
from opener.ingest.history.backfill import HistoryBackfillStage
from opener.ingest.history.mbid_resolve import MbidResolveStage
from opener.ingest.history.tag_ingest import ArtistTagStage
from opener.resolve.stage import ResolveStage
from opener.score.stage import ScoreStage


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

    steps: list[tuple[str, object]] = []

    print(f"[1/{6 if resolve_mbids else 5}] Backfilling Last.fm history...")
    r = HistoryBackfillStage().run(since_ts=since_ts) if since_ts else HistoryBackfillStage().run()
    steps.append(("backfill scrobbles", r.records_processed))

    if resolve_mbids:
        print("[2/6] Resolving artist MBIDs...")
        steps.append(("mbids resolved", MbidResolveStage().run().records_processed))

    n = len(steps) + 1
    total = 6 if resolve_mbids else 5
    print(f"[{n}/{total}] Ingesting Ticketmaster events...")
    events_run = EventSnapshotStage(TicketmasterAdapter()).run()
    steps.append(("event changes", events_run.records_processed))

    print(f"[{n + 1}/{total}] Resolving event artists to taste...")
    steps.append(("artist matches", ResolveStage().run().records_processed))

    print(f"[{n + 2}/{total}] Fetching tags for matched artists...")
    steps.append(("tag rows", ArtistTagStage(matched_only=True).run().records_processed))

    print(f"[{n + 3}/{total}] Scoring shows ({scoring_version})...")
    score_run = ScoreStage(scoring_version=scoring_version).run()
    steps.append(("scored shows", score_run.records_processed))

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
