"""Create resumable Agent state and audit event tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_agent_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_checkpoints",
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("state_json", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        if_not_exists=True,
    )
    op.create_table(
        "agent_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index(
        "agent_events_thread_idx",
        "agent_events",
        ["thread_id", "event_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("agent_events_thread_idx", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_table("agent_checkpoints")
