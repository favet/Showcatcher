"""event_description — per-event description text from venue listing pages

Revision ID: 20260622000005
Revises: 20260622000004
Create Date: 2026-06-22 00:00:05.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260622000005"
down_revision: Union[str, None] = "20260622000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "description")
