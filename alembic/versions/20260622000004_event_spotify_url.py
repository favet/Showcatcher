"""event_spotify_url — direct Spotify artist URL on events (no Last.fm match required)

Revision ID: 20260622000004
Revises: 20260622000003
Create Date: 2026-06-22 00:00:04.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260622000004"
down_revision: Union[str, None] = "20260622000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("event_spotify_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "event_spotify_url")
