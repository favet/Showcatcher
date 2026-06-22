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
from showcat.core.progress import PipelineProgress
from showcat.ingest.events.snapshot import EventSnapshotStage
from showcat.ingest.events.spotify_search import EventSpotifySearchStage
from showcat.ingest.history.backfill import HistoryBackfillStage
from showcat.ingest.history.mbid_resolve import MbidResolveStage
from showcat.ingest.history.tag_ingest import ArtistTagStage
from showcat.ingest.history.spotify_metadata import ArtistSpotifyMetadataStage
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
    """Run ingest + score end to end."""
    progress = PipelineProgress()
    progress.start()

    since_ts: int | None = None
    if backfill_days is not None:
        since_ts = int((datetime.now(UTC) - timedelta(days=backfill_days)).timestamp())

    steps: list[tuple[str, int]] = []
    total = 7 if resolve_mbids else 6

    # --- Stage 1: Backfill ---
    print(f"[1/{total}] Backfilling Last.fm history...")
    stage_prog = progress.start_stage("Last.fm History Backfill")
    try:
        backfill_kwargs = {"since_ts": since_ts} if since_ts else {}
        count = _run_stage(HistoryBackfillStage(), **backfill_kwargs)
        steps.append(("backfill scrobbles", count))
        progress.complete_stage(stage_prog, count)
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    # --- Stage 2 (optional): MBID resolve ---
    if resolve_mbids:
        print("[2/6] Resolving artist MBIDs...")
        stage_prog = progress.start_stage("MBID Resolution")
        try:
            count = _run_stage(MbidResolveStage())
            steps.append(("mbids resolved", count))
            progress.complete_stage(stage_prog, count)
        except Exception as e:
            progress.fail_stage(stage_prog, str(e))
            raise

    # --- Stage 3: Events ---
    from showcat.adapters.sources.custom import ALL_CUSTOM_ADAPTERS

    n = len(steps) + 1
    print(f"[{n}/{total}] Ingesting events from all sources...")

    all_adapters = [TicketmasterAdapter()] + [Cls() for Cls in ALL_CUSTOM_ADAPTERS]
    stage_prog = progress.start_stage("Event Scraping", total=len(all_adapters))
    total_event_changes = 0

    for i, adapter in enumerate(all_adapters):
        try:
            total_event_changes += _run_stage(EventSnapshotStage(adapter))
        except Exception as e:
            print(f"  [warn] {adapter.source_name} failed: {e}")
        progress.update_stage(stage_prog, i + 1)

    steps.append(("event changes", total_event_changes))
    progress.complete_stage(stage_prog, total_event_changes)

    # --- Stage 4: Resolve ---
    print(f"[{n + 1}/{total}] Resolving event artists to taste...")
    stage_prog = progress.start_stage("Artist Matching")
    try:
        count = _run_stage(ResolveStage())
        steps.append(("artist matches", count))
        progress.complete_stage(stage_prog, count)
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    # --- Stage 5: Tags ---
    print(f"[{n + 2}/{total}] Fetching tags for matched artists...")
    stage_prog = progress.start_stage("Tag Fetching")
    try:
        count = _run_stage(ArtistTagStage(matched_only=True))
        steps.append(("tag rows", count))
        progress.complete_stage(stage_prog, count)
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    # --- Stage 5b: Spotify Metadata ---
    print(f"[{n + 3}/{total}] Fetching Spotify metadata for matched artists...")
    stage_prog = progress.start_stage("Spotify Metadata")
    try:
        count = _run_stage(ArtistSpotifyMetadataStage(matched_only=True))
        steps.append(("spotify metadata matches", count))
        progress.complete_stage(stage_prog, count)
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    # --- Stage 6: Score ---
    print(f"[{n + 4}/{total}] Scoring shows ({scoring_version})...")
    stage_prog = progress.start_stage("Show Scoring")
    try:
        count = _run_stage(ScoreStage(scoring_version=scoring_version))
        steps.append(("scored shows", count))
        progress.complete_stage(stage_prog, count)
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    # --- Stage 7 (optional): Spotify artist URL enrichment ---
    import os
    if os.environ.get("SPOTIFY_REFRESH_TOKEN"):
        print(f"[{n + 5}/{total + 1}] Searching Spotify URLs for unmatched events...")
        stage_prog = progress.start_stage("Spotify Event URL Search")
        try:
            count = _run_stage(EventSpotifySearchStage())
            steps.append(("spotify event urls", count))
            progress.complete_stage(stage_prog, count)
        except Exception as e:
            # Non-fatal: missing token or rate-limit shouldn't abort the pipeline.
            print(f"  [warn] Spotify event URL search failed: {e}")
            progress.fail_stage(stage_prog, str(e))
    else:
        print(f"  [skip] Spotify event URL search (SPOTIFY_REFRESH_TOKEN not set)")

    # --- Stage 8: Generate Web Output ---
    print(f"[{n + 6}/{total + 2}] Generating web output...")
    stage_prog = progress.start_stage("Web Output Generation")
    try:
        from showcat.core.database import get_db_session
        from showcat.outputs.web.adapter import WebOutputAdapter

        adapter = WebOutputAdapter()
        with get_db_session() as session:
            out_path = adapter.write(session)
        steps.append(("web output", 1))
        progress.complete_stage(stage_prog, 1)
        print(f"  Written to {out_path}")
    except Exception as e:
        progress.fail_stage(stage_prog, str(e))
        raise

    progress.complete()

    print("\nDone. Summary:")
    for label, count in steps:
        print(f"  {label:<22} {count}")


if __name__ == "__main__":
    days: int | None = 365
    if len(sys.argv) > 1:
        days = None if sys.argv[1] == "full" else int(sys.argv[1])
    start = time.monotonic()
    try:
        run_pipeline(backfill_days=days)
    except Exception as e:
        print(f"\nPipeline failed: {e}")
    print(f"\nElapsed: {time.monotonic() - start:.1f}s")
