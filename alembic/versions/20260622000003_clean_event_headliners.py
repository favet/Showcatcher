"""clean_event_headliners

One-time backfill: apply title_parser.parse_title() to every existing event row
so the DB matches what new ingests will produce going forward.

Revision ID: 20260622000003
Revises: bc9324610a89
Create Date: 2026-06-22 10:00:00.000000
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '20260622000003'
down_revision: Union[str, None] = 'bc9324610a89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from showcat.adapters.sources.title_parser import (
        normalize_title,
        split_multi_artist_comma,
        split_multi_artist_plus,
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, headliner, openers FROM events")
    ).fetchall()

    updated = 0
    for row_id, headliner, openers_raw in rows:
        existing_openers: list[str] = openers_raw if isinstance(openers_raw, list) else (
            json.loads(openers_raw) if openers_raw else []
        )
        clean_headliner, w_openers, _status = normalize_title(
            headliner, existing_openers=existing_openers
        )
        clean_headliner, plus_openers = split_multi_artist_plus(
            clean_headliner, existing_openers=w_openers
        )
        clean_headliner, all_openers = split_multi_artist_comma(
            clean_headliner, existing_openers=plus_openers
        )

        if clean_headliner != headliner or all_openers != existing_openers:
            conn.execute(
                sa.text("UPDATE events SET headliner = :h, openers = :o WHERE id = :id"),
                {"h": clean_headliner, "o": json.dumps(all_openers), "id": row_id},
            )
            updated += 1

    print(f"  clean_event_headliners: updated {updated} of {len(rows)} rows")


def downgrade() -> None:
    # Title cleaning is lossy; we cannot reconstruct original dirty strings.
    pass
