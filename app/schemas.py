from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.risk import (
    OperationType,
    ProductField,
    RiskLevel,
    grade_risk,
)
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
    status: str
    variants: list[ProductVariantRead]


class ProductImportRead(BaseModel):
    imported_products: int
    imported_variants: int
    products: list[ProductRead]
