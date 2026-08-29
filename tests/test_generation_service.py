from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.domain.risk import OperationType, ProductField, RiskLevel
from app.domain.task_state import TaskState
from app.generation.service import DraftService, GenerationService
from app.generation.workflow import ALL_CONTENT_FIELDS
from app.models import Product, ProductDraft, ProductVariant, Task
from app.schemas import TaskCreate, TaskKind
from app.services import TaskService
from app.worker import run_task_workflow

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_product(
    session: TenantSession, sku: str, title: str
) -> Product:
    product = Product(
        tenant_id=session.tenant_id,
        source="merchant_csv",
        source_id=f"src-{sku}",
        sku=sku,
        title=title,
        description="Heavy cotton tee",
        category="Apparel",
        tags=["summer", "cotton"],
        images=["front.jpg"],
        meta_title=title,
        meta_description="Shop our tee",
        handle=f"handle-{sku}",
        status="draft",
        variants=[
            ProductVariant(
                tenant_id=session.tenant_id,
                sku=f"{sku}-BLK",
                options={"Color": "Black"},
                price=Decimal("29.90"),
                cost=Decimal("12.50"),
                inventory=8,
                image=None,
            )
        ],
    )
    session.add(product)
    session.flush()
    return product


def add_task(
    session: TenantSession, *, risk_level: str, product_id: UUID | None = None
) -> Task:
    task = Task(
        tenant_id=session.tenant_id,
        kind="product",
        operation_type="update",
        changed_fields=["title", "description"],
        risk_level=risk_level,
        status=TaskState.RUNNING.value,
        product_id=product_id,
    )
    session.add(task)
    session.flush()
    return task


def add_draft(
    session: TenantSession,
    task: Task,
    product: Product,
    *,
    risk_level: str,
    status: str,
    created_at: datetime,
) -> ProductDraft:
    draft = ProductDraft(
        tenant_id=session.tenant_id,
        product_id=product.id,
        task_id=task.id,
        title=product.title,
        description=product.description,
        meta_title=product.meta_title,
        meta_description=product.meta_description,
        alt_text={},
        seo_tags=[],
        risk_level=risk_level,
        status=status,
        created_at=created_at,
    )
    session.add(draft)
    session.flush()
    return draft


def test_generation_service_writes_a_pending_review_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session, "TSHIRT", "Classic T-Shirt")
        task = TaskService(session, actor="admin@example.com").create(
            TaskCreate(
                kind=TaskKind.PRODUCT,
                operation_type=OperationType.UPDATE,
                changed_fields=set(ALL_CONTENT_FIELDS),
                product_id=product.id,
            )
        )
        session.commit()

        draft = GenerationService(session).generate(task)

        assert draft.title == "Classic T-Shirt"
        assert draft.description == "Heavy cotton tee"
        assert draft.risk_level == RiskLevel.MEDIUM.value
        assert draft.status == DraftStatus.PENDING_REVIEW.value


def test_review_queue_orders_by_risk_then_creation_time() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        high_product = add_product(session, "HIGH", "High Product")
        medium_old_product = add_product(session, "MED-OLD", "Medium Old")
        medium_new_product = add_product(session, "MED-NEW", "Medium New")
        low_product = add_product(session, "LOW", "Low Product")

        high_task = add_task(session, risk_level="high", product_id=high_product.id)
        medium_old_task = add_task(
            session, risk_level="medium", product_id=medium_old_product.id
        )
        medium_new_task = add_task(
            session, risk_level="medium", product_id=medium_new_product.id
        )
        low_task = add_task(session, risk_level="low", product_id=low_product.id)

        published = add_draft(
            session,
            high_task,
            high_product,
            risk_level="high",
            status=DraftStatus.PUBLISHED.value,
            created_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        medium_new = add_draft(
            session,
            medium_new_task,
            medium_new_product,
            risk_level="medium",
            status=DraftStatus.PENDING_REVIEW.value,
            created_at=datetime(2024, 1, 1, 0, 0, 1),
        )
        low = add_draft(
            session,
            low_task,
            low_product,
            risk_level="low",
            status=DraftStatus.PENDING_REVIEW.value,
            created_at=datetime(2024, 1, 1, 0, 0, 2),
        )
        medium_old = add_draft(
            session,
            medium_old_task,
            medium_old_product,
            risk_level="medium",
            status=DraftStatus.PENDING_REVIEW.value,
            created_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        high = add_draft(
            session,
            high_task,
            high_product,
            risk_level="high",
            status=DraftStatus.PENDING_REVIEW.value,
            created_at=datetime(2024, 1, 1, 0, 0, 3),
        )

        queue = DraftService(session).review_queue()

        assert [draft.id for draft in queue] == [
            high.id,
            medium_old.id,
            medium_new.id,
            low.id,
        ]
        assert published.id not in {draft.id for draft in queue}


def test_run_task_workflow_generates_draft_and_advances_to_review() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session, "TSHIRT", "Classic T-Shirt")
        task = TaskService(session, actor="admin@example.com").create(
            TaskCreate(
                kind=TaskKind.PRODUCT,
                operation_type=OperationType.UPDATE,
                changed_fields=set(ALL_CONTENT_FIELDS),
                product_id=product.id,
            )
        )
        session.commit()
        task_id = task.id

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        status = run_task_workflow(session, task_id)
        session.commit()

        assert status == TaskState.AWAITING_REVIEW.value
        draft = session.scalar(
            select(ProductDraft).where(ProductDraft.task_id == task_id)
        )
        assert draft is not None
        assert draft.risk_level == RiskLevel.MEDIUM.value
        assert draft.status == DraftStatus.PENDING_REVIEW.value
        refreshed_task = session.get(Task, task_id)
        assert refreshed_task is not None
        assert refreshed_task.status == TaskState.AWAITING_REVIEW.value


def test_run_task_workflow_handles_a_task_without_a_product() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        task = TaskService(session, actor="admin@example.com").create(
            TaskCreate(
                kind=TaskKind.SEO,
                operation_type=OperationType.UPDATE,
                changed_fields={
                    ProductField.META_TITLE,
                    ProductField.META_DESCRIPTION,
                },
            )
        )
        session.commit()
        task_id = task.id

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        status = run_task_workflow(session, task_id)
        session.commit()

        assert status == TaskState.PUBLISHED.value
        assert (
            session.scalar(select(ProductDraft).where(ProductDraft.task_id == task_id))
            is None
        )
