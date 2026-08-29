"""Add task logs, alerting and cost attribution tables.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_model_usages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("api_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("input_tokens >= 0", name="ck_task_model_usages_input"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_task_model_usages_output"),
        sa.CheckConstraint("api_cost >= 0", name="ck_task_model_usages_cost"),
        sa.CheckConstraint(
            "tier IN ('small', 'large')", name="ck_task_model_usages_tier"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            ondelete="CASCADE",
            name="fk_task_model_usages_task",
        ),
    )
    op.create_index("ix_task_model_usages_task_id", "task_model_usages", ["task_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("dedup_key", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('task_failed', 'dead_letter', 'cost_threshold', 'worker_health')",
            name="ck_alerts_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged')", name="ck_alerts_status"
        ),
    )
    op.create_index("ix_alerts_kind", "alerts", ["kind"])
    op.create_index("ix_alerts_status", "alerts", ["status"])
    op.create_index("ix_alerts_task_id", "alerts", ["task_id"])
    op.create_index("ix_alerts_dedup_key", "alerts", ["dedup_key"])

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("worker_name", sa.String(255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("worker_name", name="uq_worker_heartbeats_worker_name"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_alerts_dedup_key", table_name="alerts")
    op.drop_index("ix_alerts_task_id", table_name="alerts")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_kind", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_task_model_usages_task_id", table_name="task_model_usages")
    op.drop_table("task_model_usages")
