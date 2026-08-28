"""Store deterministic risk-grading inputs.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "operation_type",
            sa.String(length=32),
            server_default="update",
            nullable=False,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "changed_fields",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.alter_column("tasks", "operation_type", server_default=None)
    op.alter_column("tasks", "changed_fields", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "changed_fields")
    op.drop_column("tasks", "operation_type")
