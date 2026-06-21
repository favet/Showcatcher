"""phase1_schema

Revision ID: 20260621000001
Revises: 20260621000000
Create Date: 2026-06-21 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260621000001"
down_revision: Union[str, None] = "20260621000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # artists table — canonical identity keyed by MBID or raw name
    op.create_table(
        "artists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("raw_name", sa.String(500), nullable=False),
        sa.Column("mbid", sa.String(36), nullable=True),  # UUID format
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_name", name="uq_artists_raw_name"),
    )
    op.create_index("ix_artists_mbid", "artists", ["mbid"])

    # scrobbles table — listening history, unique per play event
    op.create_table(
        "scrobbles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scrobbled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("artist_name", sa.String(500), nullable=False),
        sa.Column("track_name", sa.String(500), nullable=False),
        sa.Column("album_name", sa.String(500), nullable=True),
        sa.Column("artist_id", sa.Integer(), nullable=True),  # FK to artists
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], name="fk_scrobbles_artist_id"),
        sa.PrimaryKeyConstraint("id"),
        # Idempotency constraint: same play event never stored twice
        sa.UniqueConstraint(
            "scrobbled_at", "artist_name", "track_name", name="uq_scrobbles_play_event"
        ),
    )
    op.create_index("ix_scrobbles_scrobbled_at", "scrobbles", ["scrobbled_at"])
    op.create_index("ix_scrobbles_artist_name", "scrobbles", ["artist_name"])

    # artist_unresolved_queue — every artist that failed MBID lookup
    # Nothing is silently dropped — if resolution fails it goes here.
    op.create_table(
        "artist_unresolved_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("raw_name", sa.String(500), nullable=False),
        sa.Column("failure_reason", sa.String(100), nullable=False),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_name", name="uq_unresolved_raw_name"),
    )


def downgrade() -> None:
    op.drop_table("artist_unresolved_queue")
    op.drop_index("ix_scrobbles_artist_name", table_name="scrobbles")
    op.drop_index("ix_scrobbles_scrobbled_at", table_name="scrobbles")
    op.drop_table("scrobbles")
    op.drop_index("ix_artists_mbid", table_name="artists")
    op.drop_table("artists")
