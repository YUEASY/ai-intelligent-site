"""Per-task and per-merchant cost attribution.

Every model invocation is recorded against its task with the concrete model,
its token counts, and a derived API cost.  Cost is computed from a configured
price table rather than from the adapter, so pricing stays in one place and a
deterministic adapter still produces observable (near-zero) cost figures.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.alert_service import AlertService
from app.config import Settings, get_settings
from app.database import TenantSession
from app.domain.alert import AlertKind
from app.generation.model_adapter import ModelTier, ModelUsage
from app.models import TaskModelUsage

_COST_SCALE = Decimal("0.000001")
_MILLION = Decimal("1000000")


def compute_api_cost(usage: ModelUsage, settings: Settings) -> Decimal:
    """Derive the API cost of one invocation from the configured price table."""
    rate = (
        settings.large_model_usd_per_1m_tokens
        if usage.tier is ModelTier.LARGE
        else settings.small_model_usd_per_1m_tokens
    )
    tokens = Decimal(usage.input_tokens + usage.output_tokens)
    return (tokens * rate / _MILLION).quantize(_COST_SCALE)


def _start_of_today(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


class CostService:
    """Record model usage and answer per-merchant / per-task cost queries."""

    def __init__(
        self, session: TenantSession, settings: Settings | None = None
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    def record(
        self,
        task_id: UUID,
        usages: list[ModelUsage] | tuple[ModelUsage, ...],
    ) -> list[TaskModelUsage]:
        rows = [
            TaskModelUsage(
                tenant_id=self._session.tenant_id,
                task_id=task_id,
                tier=usage.tier.value,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                api_cost=compute_api_cost(usage, self._settings),
            )
            for usage in usages
        ]
        self._session.add_all(rows)
        self._session.flush()
        self._raise_cost_threshold_alert_if_needed()
        return rows

    def daily_cost(self, now: datetime | None = None) -> Decimal:
        start = _start_of_today(now or datetime.now(UTC))
        total = self._session.scalar(
            select(func.coalesce(func.sum(TaskModelUsage.api_cost), 0)).where(
                TaskModelUsage.created_at >= start
            )
        )
        return Decimal(total or 0)

    def total_cost(self) -> Decimal:
        total = self._session.scalar(
            select(func.coalesce(func.sum(TaskModelUsage.api_cost), 0))
        )
        return Decimal(total or 0)

    def total_tokens(self) -> int:
        total = self._session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        TaskModelUsage.input_tokens + TaskModelUsage.output_tokens
                    ),
                    0,
                )
            )
        )
        return int(total or 0)

    def task_usages(self) -> list[TaskModelUsage]:
        statement = select(TaskModelUsage).order_by(
            TaskModelUsage.created_at.desc(), TaskModelUsage.id
        )
        return list(self._session.scalars(statement))

    def task_usages_for(self, task_id: UUID) -> list[TaskModelUsage]:
        statement = (
            select(TaskModelUsage)
            .where(TaskModelUsage.task_id == task_id)
            .order_by(TaskModelUsage.created_at, TaskModelUsage.id)
        )
        return list(self._session.scalars(statement))

    def _raise_cost_threshold_alert_if_needed(self) -> None:
        daily = self.daily_cost()
        threshold = self._settings.alert_daily_cost_threshold_usd
        if daily > threshold:
            AlertService(self._session).raise_alert(
                AlertKind.COST_THRESHOLD,
                f"Daily API cost {daily} exceeded threshold {threshold}",
                dedup_key=f"cost:{_start_of_today(datetime.now(UTC)).date().isoformat()}",
            )
