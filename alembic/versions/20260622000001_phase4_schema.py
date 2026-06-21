"""phase4_schema — artist tags for the taste/adjacency engine

Revision ID: 20260622000001
Revises: 5d2ca07fd76f
Create Date: 2026-06-22 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260622000001"
down_revision: Union[str, None] = "5d2ca07fd76f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # artist_tags — per-artist genre/tag weights from Last.fm (taste vector input)
    op.create_table(
        "artist_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artist_id", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(length=200), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artist_id", "tag", name="uq_artist_tags_artist_tag"),
    )
    op.create_index("ix_artist_tags_artist_id", "artist_tags", ["artist_id"])


def downgrade() -> None:
    op.drop_index("ix_artist_tags_artist_id", table_name="artist_tags")
    op.drop_table("artist_tags")
