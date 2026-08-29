from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TenantOwned
from app.domain.draft import DraftStatus
from app.domain.product import ProductStatus
from app.domain.snapshot import SnapshotKind
from app.domain.task_state import TaskState
from app.shopify.types import ShopifyStoreStatus, WebhookEventStatus


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AdminUser(TenantOwned, Timestamped, Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_admin_users_tenant_email"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Task(TenantOwned, Timestamped, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'suggested', "
            "'awaiting_review', 'approved', "
            "'rejected', 'published', 'failed', 'rolled_back')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_tasks_risk_level",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=TaskState.PENDING.value, nullable=False, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    page_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)


class Page(TenantOwned, Timestamped, Base):
    __tablename__ = "pages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="ck_pages_status"
        ),
        UniqueConstraint("tenant_id", "handle", name="uq_pages_tenant_handle"),
        UniqueConstraint("tenant_id", "id", name="uq_pages_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_description: Mapped[str] = mapped_column(Text, nullable=False)
    seo_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    shopify_page_id: Mapped[str] = mapped_column(String(255), nullable=False)


class PageDraft(TenantOwned, Timestamped, Base):
    __tablename__ = "page_drafts"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(status.value for status in DraftStatus)!r}",
            name="ck_page_drafts_status",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_page_drafts_risk_level",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_page_drafts_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    page_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    task_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    meta_title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_description: Mapped[str] = mapped_column(Text, nullable=False)
    seo_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PageSnapshot(TenantOwned, Base):
    __tablename__ = "page_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["pages.tenant_id", "pages.id"],
            ondelete="CASCADE",
            name="fk_page_snapshots_page",
        ),
        UniqueConstraint(
            "tenant_id",
            "page_id",
            "version",
            name="uq_page_snapshots_tenant_page_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    page_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    field_diff: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    restored_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TaskAuditLog(TenantOwned, Base):
    __tablename__ = "task_audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            ondelete="CASCADE",
            name="fk_task_audit_logs_task",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Product(TenantOwned, Timestamped, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(status.value for status in ProductStatus)!r}",
            name="ck_products_status",
        ),
        UniqueConstraint(
            "tenant_id", "source", "source_id", name="uq_products_tenant_source"
        ),
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        UniqueConstraint("tenant_id", "handle", name="uq_products_tenant_handle"),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    images: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    meta_title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_description: Mapped[str] = mapped_column(Text, nullable=False)
    alt_text: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    shopify_product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProductVariant.id",
    )
    image_assets: Mapped[list["ProductImageAsset"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class ProductVariant(TenantOwned, Timestamped, Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_product_variants_price"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_product_variants_cost"),
        CheckConstraint("inventory >= 0", name="ck_product_variants_inventory"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_variants_product",
        ),
        UniqueConstraint("tenant_id", "sku", name="uq_product_variants_tenant_sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(255), nullable=False)
    options: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    inventory: Mapped[int] = mapped_column(Integer, nullable=False)
    image: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    product: Mapped[Product] = relationship(back_populates="variants")


class ProductImageAsset(TenantOwned, Timestamped, Base):
    __tablename__ = "product_image_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_image_assets_product",
        ),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "filename",
            name="uq_product_image_assets_product_filename",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[Product] = relationship(back_populates="image_assets")


class ProductDraft(TenantOwned, Timestamped, Base):
    __tablename__ = "product_drafts"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(status.value for status in DraftStatus)!r}",
            name="ck_product_drafts_status",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_product_drafts_risk_level",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_drafts_product",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            ondelete="CASCADE",
            name="fk_product_drafts_task",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_drafts_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    task_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    meta_title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_description: Mapped[str] = mapped_column(Text, nullable=False)
    alt_text: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    seo_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=DraftStatus.PENDING_REVIEW.value,
        nullable=False,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ProductSnapshot(TenantOwned, Base):
    """A versioned, diffable capture of a product's publishable state."""

    __tablename__ = "product_snapshots"
    __table_args__ = (
        CheckConstraint(
            f"kind IN {tuple(kind.value for kind in SnapshotKind)!r}",
            name="ck_product_snapshots_kind",
        ),
        CheckConstraint("version >= 0", name="ck_product_snapshots_version"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_snapshots_product",
        ),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "version",
            name="uq_product_snapshots_tenant_product_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    field_diff: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    restored_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShopifyStore(TenantOwned, Timestamped, Base):
    __tablename__ = "shopify_stores"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(status.value for status in ShopifyStoreStatus)!r}",
            name="ck_shopify_stores_status",
        ),
        UniqueConstraint("shop_domain", name="uq_shopify_stores_shop_domain"),
        UniqueConstraint("tenant_id", "id", name="uq_shopify_stores_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=ShopifyStoreStatus.CONNECTED.value,
        nullable=False,
        index=True,
    )
    encrypted_access_token: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    access_token_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShopifyOAuthState(TenantOwned, Timestamped, Base):
    __tablename__ = "shopify_oauth_states"
    __table_args__ = (
        UniqueConstraint("state_digest", name="uq_shopify_oauth_states_digest"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ShopifyWebhookEvent(TenantOwned, Base):
    __tablename__ = "shopify_webhook_events"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(status.value for status in WebhookEventStatus)!r}",
            name="ck_shopify_webhook_events_status",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "store_id"],
            ["shopify_stores.tenant_id", "shopify_stores.id"],
            ondelete="CASCADE",
            name="fk_shopify_webhook_events_store",
        ),
        UniqueConstraint("webhook_id", name="uq_shopify_webhook_events_webhook_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    webhook_id: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    api_version: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=WebhookEventStatus.RECEIVED.value,
        nullable=False,
        index=True,
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
