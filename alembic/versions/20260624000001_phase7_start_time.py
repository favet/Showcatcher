"""phase7_add_start_time — add start_time column to events table

Revision ID: 20260624000001
Revises: 20260623000001
Create Date: 2026-06-24 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260624000001"
down_revision: Union[str, None] = "20260623000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("start_time", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "start_time")
