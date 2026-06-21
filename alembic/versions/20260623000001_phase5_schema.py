"""phase5_schema — track resolution decisions for the playlist bridge

Revision ID: 20260623000001
Revises: 20260622000001
Create Date: 2026-06-23 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260623000001"
down_revision: Union[str, None] = "20260622000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # track_resolutions — every artist->track->URI decision, with the candidates
    # considered and the one chosen. The "no black box" record for track choice;
    # queryable to answer "why was track T chosen for artist A?".
    op.create_table(
        "track_resolutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artist_name", sa.String(length=500), nullable=False),
        sa.Column("track_name", sa.String(length=500), nullable=False),
        sa.Column("chosen_uri", sa.String(length=255), nullable=True),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="spotify"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artist_name", "track_name", name="uq_track_resolutions_artist_track"
        ),
    )


def downgrade() -> None:
    op.drop_table("track_resolutions")
