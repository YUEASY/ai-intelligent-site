from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.cost_service import CostService, compute_api_cost
from app.database import Base, TenantSession
from app.domain.alert import AlertKind
from app.domain.task_state import TaskState
from app.generation.model_adapter import ModelTier, ModelUsage
from app.models import Alert, Task, TaskModelUsage

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_task(session: TenantSession) -> Task:
    task = Task(
        tenant_id=TENANT_ID,
        kind="product",
        operation_type="update",
        changed_fields=["title"],
        risk_level="medium",
        status=TaskState.AWAITING_REVIEW.value,
        product_id=None,
    )
    session.add(task)
    session.flush()
    return task


def usage(
    tier: ModelTier = ModelTier.SMALL,
    tokens: int = 1000,
    model: str = "fake:small",
) -> ModelUsage:
    return ModelUsage(
        tier=tier, model=model, input_tokens=tokens, output_tokens=tokens
    )


def test_compute_api_cost_prices_by_tier() -> None:
    settings = Settings(
        small_model_usd_per_1m_tokens=Decimal("0.10"),
        large_model_usd_per_1m_tokens=Decimal("2.00"),
    )
    small = compute_api_cost(usage(tokens=1000), settings)
    large = compute_api_cost(
        usage(tier=ModelTier.LARGE, tokens=1000, model="fake:large"), settings
    )
    assert small == Decimal("0.000200")  # 2000 tokens * 0.10 / 1M
    assert large == Decimal("0.004000")  # 2000 tokens * 2.00 / 1M


def test_record_persists_usage_with_derived_cost() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        task = add_task(session)
        settings = Settings(
            small_model_usd_per_1m_tokens=Decimal("0.10"),
            large_model_usd_per_1m_tokens=Decimal("2.00"),
        )

        CostService(session, settings).record(task.id, [usage(tokens=1000)])
        session.commit()

        row = session.scalar(select(TaskModelUsage))
        assert row is not None
        assert row.task_id == task.id
        assert row.model == "fake:small"
        assert row.input_tokens == 1000
        assert row.output_tokens == 1000
        assert row.api_cost == Decimal("0.000200")


def test_record_aggregates_daily_and_total_cost() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        task = add_task(session)
        service = CostService(session)
        service.record(task.id, [usage(tokens=500)])
        service.record(task.id, [usage(tokens=500)])
        session.commit()

        assert service.daily_cost() == service.total_cost()
        assert service.total_tokens() == 2000
        assert len(service.task_usages_for(task.id)) == 2


def test_record_raises_cost_threshold_alert_once_per_day() -> None:
    engine = make_engine()
    settings = Settings(alert_daily_cost_threshold_usd=Decimal("0.000001"))
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        task = add_task(session)
        service = CostService(session, settings)

        service.record(task.id, [usage(tokens=10)])
        service.record(task.id, [usage(tokens=10)])
        session.commit()

        alerts = list(
            session.scalars(
                select(Alert).where(Alert.kind == AlertKind.COST_THRESHOLD.value)
            )
        )
        assert len(alerts) == 1
