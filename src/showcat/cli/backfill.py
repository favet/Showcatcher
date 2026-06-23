"""Full Last.fm history backfill with live browser progress.

Usage:
    python -m showcat.cli.backfill

Writes progress to $WEB_OUTPUT_DIR/backfill_progress.json so the page at
showcat.favet.net/backfill.html can display live status. After the backfill
completes, runs resolve + web output automatically.
"""
import os
import sys
import time

from showcat.core import config as _config  # noqa: F401 — loads .env
from showcat.core.database import get_db_session
from showcat.ingest.history.backfill import HistoryBackfillStage
from showcat.resolve.stage import ResolveStage
from showcat.outputs.web.adapter import WebOutputAdapter


def main() -> None:
    web_dir = os.environ.get("WEB_OUTPUT_DIR", r"C:\website\showcat")
    progress_path = os.path.join(web_dir, "backfill_progress.json")

    print(f"Progress file: {progress_path}")
    print(f"Watch live at: showcat.favet.net/backfill.html")
    print()
    print("Starting full Last.fm history backfill (no time limit)...")
    t0 = time.monotonic()

    stage = HistoryBackfillStage(progress_path=progress_path)
    record = stage.run()  # since_ts not passed → full history

    elapsed = time.monotonic() - t0
    inserted = record.records_processed or 0
    print(f"Backfill done: {inserted} new scrobbles in {elapsed:.0f}s")

    if record.status != "completed":
        print(f"Stage failed: {record.error_message}")
        sys.exit(1)

    print()
    print("Running artist resolve...")
    resolve = ResolveStage()
    resolve_record = resolve.run()
    print(f"Resolve done: {resolve_record.records_processed} matches")

    print()
    print("Regenerating web output...")
    adapter = WebOutputAdapter()
    with get_db_session() as session:
        out_path = adapter.write(session)
    print(f"Written to {out_path}")
    print()
    print(f"Total elapsed: {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
