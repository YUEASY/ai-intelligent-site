from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base, TenantSession
from app.domain.alert import AlertKind
from app.domain.task_state import TaskState
from app.health_service import HealthService
from app.models import Alert, Task, WorkerHeartbeat

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_task(session: TenantSession, status: TaskState) -> None:
    session.add(
        Task(
            tenant_id=TENANT_ID,
            kind="product",
            operation_type="update",
            changed_fields=["title"],
            risk_level="medium",
            status=status.value,
            product_id=None,
        )
    )


def settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def test_record_heartbeat_upserts_a_single_row() -> None:
    engine = make_engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        service = HealthService(session)
        service.record_heartbeat("celery-worker", now=now)
        service.record_heartbeat("celery-worker", now=now)
        session.commit()

        heartbeats = list(session.scalars(select(WorkerHeartbeat)))
        assert len(heartbeats) == 1
        assert heartbeats[0].worker_name == "celery-worker"


def test_check_reports_healthy_when_worker_fresh_and_backlog_low() -> None:
    engine = make_engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        service = HealthService(session, settings())
        service.record_heartbeat("celery-worker", now=now)
        add_task(session, TaskState.PENDING)

        report = service.check(now=now)

        assert report.healthy is True
        assert report.worker_alive is True
        assert report.backlog_count == 1
        assert session.scalar(select(Alert)) is None


def test_check_raises_alert_when_heartbeat_is_stale() -> None:
    engine = make_engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    stale = now - timedelta(seconds=600)
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        service = HealthService(session, settings())
        service.record_heartbeat("celery-worker", now=stale)

        report = service.check(now=now)
        session.commit()

        assert report.healthy is False
        assert report.worker_alive is False
        alert = session.scalar(
            select(Alert).where(Alert.kind == AlertKind.WORKER_HEALTH.value)
        )
        assert alert is not None
        assert "heartbeat" in alert.message


def test_check_raises_alert_when_backlog_exceeds_threshold() -> None:
    engine = make_engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        service = HealthService(
            session, settings(alert_worker_backlog_threshold=1)
        )
        service.record_heartbeat("celery-worker", now=now)
        add_task(session, TaskState.PENDING)
        add_task(session, TaskState.RUNNING)

        report = service.check(now=now)
        session.commit()

        assert report.healthy is False
        assert report.backlog_count == 2
        alert = session.scalar(
            select(Alert).where(Alert.kind == AlertKind.WORKER_HEALTH.value)
        )
        assert alert is not None
        assert "backlog" in alert.message
