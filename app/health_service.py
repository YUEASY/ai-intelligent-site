"""Service health monitoring: worker heartbeat + task backlog.

The Celery worker records a heartbeat whenever it processes a task; a monitor
(or the admin console) then checks that the heartbeat is fresh and the task
backlog is within threshold.  A breach raises a single ``worker_health`` alert.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.alert_service import AlertService
from app.config import Settings, get_settings
from app.database import TenantSession
from app.domain.alert import AlertKind
from app.domain.task_state import TaskState
from app.models import Task, WorkerHeartbeat

BACKLOG_STATUSES = {TaskState.PENDING.value, TaskState.RUNNING.value}


def _naive_utc(value: datetime | None = None) -> datetime:
    """Return `value` (or now) as a naive UTC datetime for safe comparison."""
    return (value or datetime.now(UTC)).replace(tzinfo=None)


@dataclass(frozen=True)
class WorkerHealth:
    worker_alive: bool
    heartbeat_age_seconds: float | None
    backlog_count: int
    healthy: bool
    reason: str | None


class HealthService:
    def __init__(
        self, session: TenantSession, settings: Settings | None = None
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    def record_heartbeat(
        self, worker_name: str, now: datetime | None = None
    ) -> WorkerHeartbeat:
        seen_at = _naive_utc(now)
        heartbeat = self._session.scalar(
            select(WorkerHeartbeat).where(WorkerHeartbeat.worker_name == worker_name)
        )
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(
                worker_name=worker_name, last_seen_at=seen_at
            )
            self._session.add(heartbeat)
        else:
            heartbeat.last_seen_at = seen_at
        self._session.flush()
        return heartbeat

    def check(self, now: datetime | None = None) -> WorkerHealth:
        current = _naive_utc(now)
        heartbeat = self._session.scalar(
            select(WorkerHeartbeat)
            .order_by(WorkerHeartbeat.last_seen_at.desc())
            .limit(1)
        )
        backlog = (
            self._session.scalar(
                select(func.count(Task.id)).where(Task.status.in_(BACKLOG_STATUSES))
            )
            or 0
        )

        age: float | None = None
        if heartbeat is not None:
            age = (
                current - heartbeat.last_seen_at.replace(tzinfo=None)
            ).total_seconds()

        timeout = self._settings.alert_worker_heartbeat_timeout_seconds
        worker_alive = age is not None and 0 <= age <= timeout

        reasons: list[str] = []
        if not worker_alive:
            reasons.append("worker heartbeat is stale or missing")
        if backlog > self._settings.alert_worker_backlog_threshold:
            reasons.append(
                f"task backlog {backlog} exceeds "
                f"{self._settings.alert_worker_backlog_threshold}"
            )

        healthy = not reasons
        if not healthy:
            AlertService(self._session).raise_alert(
                AlertKind.WORKER_HEALTH,
                "; ".join(reasons),
                dedup_key="worker_health",
            )
        return WorkerHealth(
            worker_alive=worker_alive,
            heartbeat_age_seconds=age,
            backlog_count=backlog,
            healthy=healthy,
            reason="; ".join(reasons) if reasons else None,
        )
