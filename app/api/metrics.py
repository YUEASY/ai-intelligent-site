"""Dashboard metrics (analysis-only, never real-time alerts).

Ranking, token trends, and task counts surface here.  This endpoint reports
trend data from the database; it does not raise alerts.  Worker health is a
separate concern and is reported by ``GET /metrics/health`` (which also raises
an idempotent alert through the monitor when the worker is unhealthy).
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.alert_service import AlertService
from app.config import Settings, get_settings
from app.cost_service import CostService
from app.database import TenantSession
from app.dependencies import RequestContext, get_request_context
from app.domain.alert import AlertStatus
from app.domain.task_state import TaskState
from app.health_service import HealthService
from app.models import Task, TaskModelUsage
from app.schemas import (
    AlertRead,
    DailyTokenRead,
    DashboardMetricsRead,
    WorkerHealthRead,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=DashboardMetricsRead)
def dashboard_metrics(
    context: Annotated[RequestContext, Depends(get_request_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardMetricsRead:
    session = context.session
    tasks_total = session.scalar(select(func.count(Task.id))) or 0
    tasks_published = (
        session.scalar(
            select(func.count(Task.id)).where(
                Task.status == TaskState.PUBLISHED.value
            )
        )
        or 0
    )
    tasks_failed = (
        session.scalar(
            select(func.count(Task.id)).where(Task.status == TaskState.FAILED.value)
        )
        or 0
    )
    terminal = tasks_published + tasks_failed
    success_rate = (tasks_published / terminal) if terminal else None

    cost = CostService(session, settings)
    open_alerts = [
        alert
        for alert in AlertService(session).list_alerts()
        if alert.status == AlertStatus.OPEN.value
    ]
    return DashboardMetricsRead(
        tasks_total=tasks_total,
        tasks_published=tasks_published,
        tasks_failed=tasks_failed,
        success_rate=success_rate,
        tokens_total=cost.total_tokens(),
        cost_total=cost.total_cost(),
        daily=_daily_tokens(session),
        open_alerts=[AlertRead.model_validate(alert) for alert in open_alerts],
    )


@router.get("/health", response_model=WorkerHealthRead)
def worker_health(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> WorkerHealthRead:
    report = HealthService(context.session).check()
    return WorkerHealthRead(
        worker_alive=report.worker_alive,
        heartbeat_age_seconds=report.heartbeat_age_seconds,
        backlog_count=report.backlog_count,
        healthy=report.healthy,
        reason=report.reason,
    )


def _daily_tokens(session: TenantSession) -> list[DailyTokenRead]:
    rows = session.execute(
        select(
            TaskModelUsage.created_at,
            TaskModelUsage.input_tokens,
            TaskModelUsage.output_tokens,
            TaskModelUsage.api_cost,
        ).order_by(TaskModelUsage.created_at)
    ).all()
    buckets: dict[str, dict[str, Decimal | int]] = {}
    for created_at, input_tokens, output_tokens, api_cost in rows:
        day = created_at.date().isoformat()
        bucket = buckets.setdefault(day, {"tokens": 0, "cost": Decimal("0")})
        bucket["tokens"] = (
            int(bucket["tokens"]) + int(input_tokens) + int(output_tokens)
        )
        bucket["cost"] = Decimal(bucket["cost"]) + Decimal(api_cost)
    return [
        DailyTokenRead(
            date=day,
            tokens=int(values["tokens"]),
            cost=Decimal(values["cost"]),
        )
        for day, values in sorted(buckets.items())
    ]
