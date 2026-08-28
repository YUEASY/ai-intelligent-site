from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TenantOwned
from app.domain.task_state import TaskState


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
            "status IN ('pending', 'running', 'awaiting_review', 'approved', "
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


class ShopifyStore(TenantOwned, Timestamped, Base):
    __tablename__ = "shopify_stores"
    __table_args__ = (
        CheckConstraint(
            "status IN ('connected', 'disconnected', 'error')",
            name="ck_shopify_stores_status",
        ),
        UniqueConstraint("shop_domain", name="uq_shopify_stores_shop_domain"),
        UniqueConstraint("tenant_id", "id", name="uq_shopify_stores_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="connected", nullable=False, index=True
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
            "status IN ('received', 'processed', 'dead_letter')",
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
        String(32), default="received", nullable=False, index=True
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
