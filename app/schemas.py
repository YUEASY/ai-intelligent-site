from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.task_state import TaskState


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


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
    kind: str = Field(min_length=1, max_length=100)
    risk_level: RiskLevel


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    kind: str
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
