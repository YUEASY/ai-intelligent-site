"""Add AI-generated product drafts and task-to-product linkage.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("product_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_tasks_product_id"), "tasks", ["product_id"]
    )

    op.create_table(
        "product_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("meta_title", sa.String(length=255), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=False),
        sa.Column("alt_text", sa.JSON(), nullable=False),
        sa.Column("seo_tags", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_product_drafts_risk_level",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'published', 'rejected')",
            name="ck_product_drafts_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_drafts_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_product_drafts_task",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_product_drafts_tenant_id"
        ),
    )
    op.create_index(
        op.f("ix_product_drafts_product_id"),
        "product_drafts",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_drafts_status"),
        "product_drafts",
        ["status"],
    )
    op.create_index(
        op.f("ix_product_drafts_task_id"),
        "product_drafts",
        ["task_id"],
    )
    op.create_index(
        op.f("ix_product_drafts_tenant_id"),
        "product_drafts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_drafts_tenant_id"), table_name="product_drafts"
    )
    op.drop_index(
        op.f("ix_product_drafts_task_id"), table_name="product_drafts"
    )
    op.drop_index(
        op.f("ix_product_drafts_status"), table_name="product_drafts"
    )
    op.drop_index(
        op.f("ix_product_drafts_product_id"), table_name="product_drafts"
    )
    op.drop_table("product_drafts")
    op.drop_index(op.f("ix_tasks_product_id"), table_name="tasks")
    op.drop_column("tasks", "product_id")
