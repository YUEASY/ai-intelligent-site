from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.api.alerts import router as alerts_router
from app.api.costs import router as costs_router
from app.api.metrics import router as metrics_router
from app.api.tasks import router as tasks_router
from app.database import Base, TenantSession
from app.dependencies import RequestContext, get_request_context
from app.domain.alert import AlertKind
from app.domain.task_state import TaskState
from app.models import AdminUser, Alert, Task, TaskAuditLog, TaskModelUsage

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")


def make_client() -> tuple[TestClient, Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_A
    ) as session:
        task = Task(
            tenant_id=TENANT_A,
            kind="product",
            operation_type="update",
            changed_fields=["title"],
            risk_level="medium",
            status=TaskState.FAILED.value,
            product_id=None,
            last_error="boom",
        )
        session.add(task)
        session.flush()
        session.add(
            TaskAuditLog(
                tenant_id=TENANT_A,
                task_id=task.id,
                actor="admin@example.com",
                from_status=TaskState.PENDING.value,
                to_status=TaskState.RUNNING.value,
            )
        )
        session.add(
            TaskModelUsage(
                tenant_id=TENANT_A,
                task_id=task.id,
                tier="small",
                model="fake:small",
                input_tokens=10,
                output_tokens=20,
                api_cost=Decimal("0.000005"),
            )
        )
        session.add(
            Alert(
                tenant_id=TENANT_A,
                kind=AlertKind.TASK_FAILED.value,
                status="open",
                message=f"Task {task.id} failed: boom",
                task_id=task.id,
                dedup_key=f"task:{task.id}",
            )
        )
        session.commit()

    def request_context() -> Iterator[RequestContext]:
        admin = AdminUser(
            id=uuid4(),
            tenant_id=TENANT_A,
            email="admin@example.com",
            password_hash="unused",
        )
        with TenantSession(
            bind=engine, expire_on_commit=False, tenant_id=TENANT_A
        ) as session:
            yield RequestContext(
                tenant_id=TENANT_A,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(costs_router, prefix="/api/v1")
    app.include_router(alerts_router, prefix="/api/v1")
    app.include_router(metrics_router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    return TestClient(app), engine


def test_task_timeline_reports_audit_log_and_cost() -> None:
    client, _ = make_client()
    task_id = client.get("/api/v1/tasks").json()[0]["id"]

    response = client.get(f"/api/v1/tasks/{task_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "failed"
    assert body["task"]["last_error"] == "boom"
    assert len(body["audit_log"]) == 1
    assert body["audit_log"][0]["to_status"] == "running"
    assert len(body["costs"]) == 1
    assert body["costs"][0]["model"] == "fake:small"


def test_cost_overview_reports_merchant_and_task_cost() -> None:
    client, _ = make_client()

    response = client.get("/api/v1/costs")

    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens"] == 30
    assert Decimal(body["total_cost"]) == Decimal("0.000005")
    assert len(body["tasks"]) == 1
    assert body["daily_threshold"] is not None


def test_alerts_list_and_acknowledge() -> None:
    client, _ = make_client()

    listing = client.get("/api/v1/alerts")
    assert listing.status_code == 200
    alert_id = listing.json()[0]["id"]
    assert listing.json()[0]["status"] == "open"

    acknowledged = client.post(f"/api/v1/alerts/{alert_id}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"


def test_metrics_report_counts_and_open_alerts() -> None:
    client, _ = make_client()

    response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["tasks_total"] == 1
    assert body["tasks_failed"] == 1
    assert body["success_rate"] == 0.0
    assert body["tokens_total"] == 30
    assert len(body["open_alerts"]) == 1
    assert len(body["daily"]) == 1
    assert body["daily"][0]["tokens"] == 30
