"""Add first-class page SEO lifecycle.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('pending', 'running', 'suggested', 'awaiting_review', 'approved', "
        "'rejected', 'published', 'failed', 'rolled_back')",
    )
    op.add_column("tasks", sa.Column("page_id", sa.Uuid(), nullable=True))
    op.create_index("ix_tasks_page_id", "tasks", ["page_id"])
    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("handle", sa.String(255), nullable=False),
        sa.Column("meta_title", sa.String(255), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=False),
        sa.Column("seo_tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("shopify_page_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "handle", name="uq_pages_tenant_handle"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pages_tenant_id"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="ck_pages_status"
        ),
    )
    op.create_table(
        "page_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("meta_title", sa.String(255), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=False),
        sa.Column("seo_tags", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rejection_reason", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_page_drafts_tenant_id"),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'published', 'rejected', "
            "'rolled_back')",
            name="ck_page_drafts_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_page_drafts_risk_level",
        ),
    )
    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("field_diff", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("restored_version", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "page_id",
            "version",
            name="uq_page_snapshots_tenant_page_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
            name="fk_page_snapshots_page",
        ),
    )


def downgrade() -> None:
    op.drop_table("page_snapshots")
    op.drop_table("page_drafts")
    op.drop_table("pages")
    op.drop_index("ix_tasks_page_id", table_name="tasks")
    op.drop_column("tasks", "page_id")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('pending', 'running', 'awaiting_review', 'approved', "
        "'rejected', 'published', 'failed', 'rolled_back')",
    )
