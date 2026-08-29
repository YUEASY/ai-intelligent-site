"""Add canonical products and variants.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("meta_title", sa.String(length=255), nullable=False),
        sa.Column("meta_description", sa.Text(), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
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
            "status IN ('draft', 'active', 'archived')",
            name="ck_products_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "handle", name="uq_products_tenant_handle"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        sa.UniqueConstraint(
            "tenant_id", "source", "source_id", name="uq_products_tenant_source"
        ),
    )
    op.create_index(op.f("ix_products_status"), "products", ["status"])
    op.create_index(op.f("ix_products_tenant_id"), "products", ["tenant_id"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("inventory", sa.Integer(), nullable=False),
        sa.Column("image", sa.String(length=2048), nullable=True),
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
            "cost IS NULL OR cost >= 0", name="ck_product_variants_cost"
        ),
        sa.CheckConstraint("inventory >= 0", name="ck_product_variants_inventory"),
        sa.CheckConstraint("price >= 0", name="ck_product_variants_price"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_variants_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "sku", name="uq_product_variants_tenant_sku"
        ),
    )
    op.create_index(
        op.f("ix_product_variants_product_id"),
        "product_variants",
        ["product_id"],
    )
    op.create_index(
        op.f("ix_product_variants_tenant_id"),
        "product_variants",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_variants_tenant_id"), table_name="product_variants"
    )
    op.drop_index(
        op.f("ix_product_variants_product_id"), table_name="product_variants"
    )
    op.drop_table("product_variants")
    op.drop_index(op.f("ix_products_tenant_id"), table_name="products")
    op.drop_index(op.f("ix_products_status"), table_name="products")
    op.drop_table("products")
