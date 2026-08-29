from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.draft import DraftStatus
from app.domain.product import ProductStatus
from app.domain.review import RejectionReason
from app.domain.risk import (
    OperationType,
    ProductField,
    RiskLevel,
    grade_risk,
)
from app.domain.snapshot import SnapshotKind
from app.domain.task_state import TaskState


class TaskKind(StrEnum):
    PRODUCT = "product"
    SEO = "seo"


class LoginRequest(BaseModel):
    tenant_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminRead(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    operation_type: OperationType
    changed_fields: set[ProductField] = Field(default_factory=set)
    product_id: UUID | None = None
    page_id: UUID | None = None

    @model_validator(mode="after")
    def validate_risk_input(self) -> "TaskCreate":
        grade_risk(self.operation_type, self.changed_fields)
        return self


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    kind: TaskKind
    operation_type: OperationType
    changed_fields: list[ProductField]
    risk_level: RiskLevel
    status: TaskState
    last_error: str | None
    product_id: UUID | None
    page_id: UUID | None
    created_at: datetime
    updated_at: datetime


class TaskTransitionRequest(BaseModel):
    target: TaskState


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    task_id: UUID
    actor: str
    from_status: TaskState
    to_status: TaskState
    occurred_at: datetime


class ProductVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    options: dict[str, str]
    price: Decimal
    cost: Decimal | None
    inventory: int
    image: str | None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    source: str
    source_id: str
    sku: str
    title: str
    description: str
    category: str
    tags: list[str]
    images: list[str]
    meta_title: str
    meta_description: str
    handle: str
    status: ProductStatus
    variants: list[ProductVariantRead]


class ProductImportRead(BaseModel):
    imported_products: int
    imported_variants: int
    imported_images: int
    products: list[ProductRead]


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    title: str
    body_html: str
    handle: str
    meta_title: str
    meta_description: str
    seo_tags: list[str]
    status: str
    shopify_page_id: str


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    product_id: UUID
    task_id: UUID
    title: str
    description: str
    meta_title: str
    meta_description: str
    alt_text: dict[str, str]
    seo_tags: list[str]
    risk_level: RiskLevel
    status: DraftStatus
    rejection_reason: RejectionReason | None = None
    created_at: datetime
    updated_at: datetime


class DraftEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    alt_text: dict[str, str] | None = None
    seo_tags: list[str] | None = None
    body_html: str | None = None


class PageDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    page_id: UUID
    task_id: UUID
    title: str
    body_html: str
    meta_title: str
    meta_description: str
    seo_tags: list[str]
    risk_level: RiskLevel
    status: DraftStatus
    rejection_reason: RejectionReason | None = None
    created_at: datetime
    updated_at: datetime


class SeoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_title: bool = False


class ReviewQueueItemRead(BaseModel):
    """A review-queue item enriched with its task kind and lifecycle status."""

    id: UUID
    tenant_id: UUID
    product_id: UUID | None = None
    page_id: UUID | None = None
    task_id: UUID
    title: str
    description: str = ""
    body_html: str = ""
    meta_title: str
    meta_description: str
    alt_text: dict[str, str] = Field(default_factory=dict)
    seo_tags: list[str]
    risk_level: RiskLevel
    status: DraftStatus
    rejection_reason: RejectionReason | None = None
    created_at: datetime
    updated_at: datetime
    kind: TaskKind
    task_status: TaskState
    task_error: str | None = None


class ReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_ids: list[UUID] = Field(min_length=1)


class RejectRequest(ReviewActionRequest):
    reason: RejectionReason


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    version: int
    kind: SnapshotKind
    payload: dict[str, object]
    field_diff: dict[str, object]
    actor: str
    restored_version: int | None
    created_at: datetime


class PageSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    page_id: UUID
    version: int
    kind: SnapshotKind
    payload: dict[str, object]
    field_diff: dict[str, object]
    actor: str
    restored_version: int | None
    created_at: datetime


class PublishRead(BaseModel):
    draft: DraftRead | PageDraftRead
    task: TaskRead
    snapshot: SnapshotRead | PageSnapshotRead
    remote_id: str


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class RollbackRead(BaseModel):
    product: ProductRead
    task: TaskRead | None
    snapshot: SnapshotRead


class PageRollbackRead(BaseModel):
    page: PageRead
    task: TaskRead | None
    snapshot: PageSnapshotRead
