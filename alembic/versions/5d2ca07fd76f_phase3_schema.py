"""phase3_schema

Revision ID: 5d2ca07fd76f
Revises: 20260621000002
Create Date: 2026-06-21 05:37:00.437435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d2ca07fd76f'
down_revision: Union[str, None] = '20260621000002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("matched_name", sa.String(length=255), nullable=False),
        sa.Column("match_type", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "artist_id", name="uq_event_matches_event_artist"),
    )
    op.create_table(
        "event_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.String(length=50), nullable=False),
        sa.Column("score_total", sa.Float(), nullable=False),
        sa.Column("taste_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("adjacency_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("discovery_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("recency_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("distance_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "scoring_version", name="uq_event_scores_event_version"),
    )


def downgrade() -> None:
    op.drop_table("event_scores")
    op.drop_table("event_matches")
