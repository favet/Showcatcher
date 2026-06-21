"""End-to-end pipeline driver.

Runs the discovery slice in order: resolve -> score -> digest. Stages still
couple only through the database (no stage imports another); this driver is
just the conductor that invokes them in sequence and renders the output.

Determinism: pass a fixed `reference_time` to pin the affinity decay so the
produced digest is reproducible (used by the golden pipeline test).
"""
from datetime import datetime

from opener.core import database
from opener.outputs.digest.adapter import Digest, DigestOutputAdapter
from opener.resolve.stage import ResolveStage
from opener.score.stage import ScoreStage


def run_pipeline(reference_time: datetime | None = None) -> Digest:
    """Resolve event artists, score matched shows, and build the ticket digest.

    Returns the structured Digest artifact. Each stage runs through the
    BaseStage lifecycle (run-ledger + dead-letter), so failures are observable.
    """
    ResolveStage().run()
    ScoreStage(reference_time=reference_time).run()

    with database.get_db_session() as session:
        return DigestOutputAdapter().build(session)


if __name__ == "__main__":
    digest = run_pipeline()
    print(DigestOutputAdapter().render_text(digest))
