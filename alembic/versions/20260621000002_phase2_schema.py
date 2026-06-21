"""phase2_schema

Revision ID: 20260621000002
Revises: 20260621000001
Create Date: 2026-06-21 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260621000002"
down_revision: Union[str, None] = "20260621000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # events — normalised upcoming show records
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("headliner", sa.String(500), nullable=False),
        sa.Column("openers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("venue", sa.String(255), nullable=False),
        sa.Column("on_sale_date", sa.Date(), nullable=True),
        sa.Column("ticket_url", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_events_source_id"),
    )
    op.create_index("ix_events_date", "events", ["date"])
    op.create_index("ix_events_source", "events", ["source"])

    # event_snapshots — raw captured API/scrape responses per run
    op.create_table(
        "event_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_snapshots_source", "event_snapshots", ["source"])

    # event_changes — detected changes between snapshots
    op.create_table(
        "event_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("event_source_id", sa.String(255), nullable=False),
        sa.Column("change_type", sa.String(50), nullable=False),  # 'new_event', 'opener_added', etc.
        sa.Column("change_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        # Idempotency: same change can't be recorded twice
        sa.UniqueConstraint("source", "event_source_id", "change_type", "detected_at",
                            name="uq_event_changes_unique"),
    )

    # source_health — per-source last-success and anomaly tracking
    op.create_table(
        "source_health",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(100), nullable=False, unique=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_count", sa.Integer(), nullable=True),
        sa.Column("trailing_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),  # list of recent counts
        sa.Column("anomaly_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("anomaly_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("source_health")
    op.drop_table("event_changes")
    op.drop_index("ix_event_snapshots_source", table_name="event_snapshots")
    op.drop_table("event_snapshots")
    op.drop_index("ix_events_source", table_name="events")
    op.drop_index("ix_events_date", table_name="events")
    op.drop_table("events")
