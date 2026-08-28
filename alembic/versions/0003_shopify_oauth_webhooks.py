"""Add Shopify OAuth installations and durable webhook events.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopify_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("encrypted_access_token", sa.LargeBinary(), nullable=True),
        sa.Column("access_token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "status IN ('connected', 'disconnected', 'error')",
            name="ck_shopify_stores_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_domain", name="uq_shopify_stores_shop_domain"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_shopify_stores_tenant_id"),
    )
    op.create_index(op.f("ix_shopify_stores_status"), "shopify_stores", ["status"])
    op.create_index(
        op.f("ix_shopify_stores_tenant_id"), "shopify_stores", ["tenant_id"]
    )

    op.create_table(
        "shopify_oauth_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_digest", name="uq_shopify_oauth_states_digest"),
    )
    op.create_index(
        op.f("ix_shopify_oauth_states_tenant_id"),
        "shopify_oauth_states",
        ["tenant_id"],
    )

    op.create_table(
        "shopify_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("webhook_id", sa.String(length=255), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("api_version", sa.String(length=32), nullable=False),
        sa.Column("raw_payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'dead_letter')",
            name="ck_shopify_webhook_events_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "store_id"],
            ["shopify_stores.tenant_id", "shopify_stores.id"],
            name="fk_shopify_webhook_events_store",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webhook_id", name="uq_shopify_webhook_events_webhook_id"),
    )
    op.create_index(
        op.f("ix_shopify_webhook_events_status"),
        "shopify_webhook_events",
        ["status"],
    )
    op.create_index(
        op.f("ix_shopify_webhook_events_store_id"),
        "shopify_webhook_events",
        ["store_id"],
    )
    op.create_index(
        op.f("ix_shopify_webhook_events_tenant_id"),
        "shopify_webhook_events",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shopify_webhook_events_tenant_id"),
        table_name="shopify_webhook_events",
    )
    op.drop_index(
        op.f("ix_shopify_webhook_events_store_id"),
        table_name="shopify_webhook_events",
    )
    op.drop_index(
        op.f("ix_shopify_webhook_events_status"),
        table_name="shopify_webhook_events",
    )
    op.drop_table("shopify_webhook_events")
    op.drop_index(
        op.f("ix_shopify_oauth_states_tenant_id"),
        table_name="shopify_oauth_states",
    )
    op.drop_table("shopify_oauth_states")
    op.drop_index(op.f("ix_shopify_stores_tenant_id"), table_name="shopify_stores")
    op.drop_index(op.f("ix_shopify_stores_status"), table_name="shopify_stores")
    op.drop_table("shopify_stores")
