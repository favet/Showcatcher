"""phase8_ticket_provider — add ticket_provider column to events table

Records which ticketing platform an event's ticket_url points at
(etix/dice/eventbrite/ticketmaster/venue/…), driving the de-Ticketmaster link
preference and the UI provider badge.

Revision ID: 20260621000003
Revises: c8f804835b2b
Create Date: 2026-06-21 00:00:03.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260621000003"
down_revision: Union[str, None] = "c8f804835b2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("ticket_provider", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "ticket_provider")
