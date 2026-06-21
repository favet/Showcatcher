"""Add doors and show times

Revision ID: c8f804835b2b
Revises: 20260624000001
Create Date: 2026-06-21 11:56:40.578125

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c8f804835b2b'
down_revision: Union[str, None] = '20260624000001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename start_time to show_time
    op.alter_column('events', 'start_time', new_column_name='show_time')
    # Add doors_time
    op.add_column('events', sa.Column('doors_time', postgresql.TIME(), nullable=True))

def downgrade() -> None:
    # Drop doors_time
    op.drop_column('events', 'doors_time')
    # Rename show_time back to start_time
    op.alter_column('events', 'show_time', new_column_name='start_time')
