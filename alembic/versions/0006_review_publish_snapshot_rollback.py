"""Add review decisions, Shopify product ids, and version snapshots.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("shopify_product_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "product_drafts",
        sa.Column("rejection_reason", sa.String(length=32), nullable=True),
    )
    op.drop_constraint("ck_product_drafts_status", "product_drafts", type_="check")
    op.create_check_constraint(
        "ck_product_drafts_status",
        "product_drafts",
        "status IN ('pending_review', 'approved', 'published', 'rejected', "
        "'rolled_back')",
    )

    op.create_table(
        "product_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("field_diff", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=False),
        sa.Column("restored_version", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('publish', 'rollback')",
            name="ck_product_snapshots_kind",
        ),
        sa.CheckConstraint("version >= 0", name="ck_product_snapshots_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_snapshots_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "version",
            name="uq_product_snapshots_tenant_product_version",
        ),
    )
    op.create_index(
        op.f("ix_product_snapshots_product_id"),
        "product_snapshots",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_snapshots_tenant_id"),
        "product_snapshots",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_snapshots_tenant_id"), table_name="product_snapshots"
    )
    op.drop_index(
        op.f("ix_product_snapshots_product_id"), table_name="product_snapshots"
    )
    op.drop_table("product_snapshots")

    op.drop_constraint("ck_product_drafts_status", "product_drafts", type_="check")
    op.create_check_constraint(
        "ck_product_drafts_status",
        "product_drafts",
        "status IN ('pending_review', 'published', 'rejected')",
    )
    op.drop_column("product_drafts", "rejection_reason")
    op.drop_column("products", "shopify_product_id")
