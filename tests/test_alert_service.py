from uuid import UUID

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.alert_service import AlertNotFoundError, AlertService
from app.database import Base, TenantSession
from app.domain.alert import AlertKind, AlertStatus
from app.domain.task_state import TaskState
from app.models import Alert, Task
from app.services import TaskService

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_raise_alert_creates_an_open_alert() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        alert = AlertService(session).raise_alert(
            AlertKind.TASK_FAILED, "Task failed", dedup_key="task:1"
        )
        session.commit()

        assert alert.kind == AlertKind.TASK_FAILED.value
        assert alert.status == AlertStatus.OPEN.value
        assert alert.dedup_key == "task:1"


def test_raise_alert_deduplicates_while_open() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        service = AlertService(session)
        first = service.raise_alert(
            AlertKind.DEAD_LETTER, "dead letter", dedup_key="webhook:1"
        )
        second = service.raise_alert(
            AlertKind.DEAD_LETTER, "dead letter again", dedup_key="webhook:1"
        )
        session.commit()

        assert first.id == second.id
        alerts = list(session.scalars(select(Alert)))
        assert len(alerts) == 1


def test_acknowledge_moves_an_open_alert() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        alert = AlertService(session).raise_alert(
            AlertKind.WORKER_HEALTH, "worker down"
        )
        session.commit()

        acknowledged = AlertService(session).acknowledge(alert.id)
        session.commit()

        assert acknowledged.status == AlertStatus.ACKNOWLEDGED.value
        assert acknowledged.acknowledged_at is not None


def test_acknowledge_unknown_alert_raises() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        try:
            AlertService(session).acknowledge(UUID(int=0))
        except AlertNotFoundError:
            return
        raise AssertionError("expected AlertNotFoundError")


def test_task_failure_raises_a_task_failed_alert() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        task = Task(
            tenant_id=TENANT_ID,
            kind="product",
            operation_type="update",
            changed_fields=["title"],
            risk_level="medium",
            status=TaskState.RUNNING.value,
            product_id=None,
        )
        session.add(task)
        session.flush()

        TaskService(session, actor="admin@example.com").fail(task.id, "boom")
        session.commit()

        alert = session.scalar(
            select(Alert).where(Alert.kind == AlertKind.TASK_FAILED.value)
        )
        assert alert is not None
        assert alert.task_id == task.id
        assert "boom" in alert.message
