from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.domain.product import ProductStatus
from app.domain.risk import OperationType, ProductField
from app.domain.snapshot import SnapshotKind
from app.domain.task_state import TaskState
from app.generation.model_adapter import (
    GeneratedContent,
    ModelInvocation,
    ModelTier,
    ModelUsage,
)
from app.generation.workflow import ProductWorkflow
from app.models import Product, ProductDraft, ProductSnapshot, ProductVariant, Task
from app.platform import (
    NoopPlatformAdapter,
    PlatformReceipt,
    RecordingPlatformAdapter,
)
from app.publish_service import PublishService
from app.schemas import TaskCreate, TaskKind
from app.seo import (
    SEO_ALL_FIELDS,
    SEO_LOW_RISK_FIELDS,
    SeoProductNotPublished,
    SeoService,
)
from app.services import TaskService
from app.worker import run_task_workflow

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

SEO_LOW_FIELDS = set(SEO_LOW_RISK_FIELDS)
SEO_WITH_TITLE_FIELDS = set(SEO_ALL_FIELDS)


class FakeSeoModelAdapter:
    """Fake LLM emitting a deterministic, fact-safe SEO suggestion."""

    def generate(
        self,
        tier: ModelTier,
        product: object,
        fields: frozenset[ProductField],
    ) -> ModelInvocation:
        del product
        content = GeneratedContent()
        if ProductField.TITLE in fields:
            content.title = "Optimized Classic T-Shirt"
        if ProductField.META_TITLE in fields:
            content.meta_title = "Optimized Meta Title"
        if ProductField.META_DESCRIPTION in fields:
            content.meta_description = "Optimized meta description"
        if ProductField.ALT_TEXT in fields:
            content.alt_text = {"front.jpg": "Optimized alt text"}
        if ProductField.SEO_TAGS in fields:
            content.seo_tags = ["optimized", "summer"]
        return ModelInvocation(
            content=content,
            usage=ModelUsage(
                tier=tier,
                model=f"fake:{tier.value}",
                input_tokens=1,
                output_tokens=1,
            ),
        )


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_published_product(session: TenantSession) -> Product:
    product = Product(
        tenant_id=session.tenant_id,
        source="merchant_csv",
        source_id="product-1",
        sku="TSHIRT",
        title="Classic T-Shirt",
        description="Heavy cotton tee",
        category="Apparel",
        tags=["summer", "cotton"],
        images=["front.jpg"],
        meta_title="Old Meta Title",
        meta_description="Old meta description",
        alt_text={"front.jpg": "Old alt"},
        handle="classic-t-shirt",
        status=ProductStatus.ACTIVE.value,
        shopify_product_id="shopify-123",
        variants=[
            ProductVariant(
                tenant_id=session.tenant_id,
                sku="TSHIRT-BLK-S",
                options={"Color": "Black", "Size": "S"},
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


def add_seo_task(
    session: TenantSession,
    product: Product,
    *,
    fields: set[ProductField],
    risk_level: str,
) -> Task:
    task = Task(
        tenant_id=session.tenant_id,
        kind=TaskKind.SEO.value,
        operation_type="update",
        changed_fields=sorted(field.value for field in fields),
        risk_level=risk_level,
        status=TaskState.RUNNING.value,
        product_id=product.id,
    )
    session.add(task)
    session.flush()
    return task


def make_service(session: TenantSession) -> SeoService:
    workflow = ProductWorkflow(FakeSeoModelAdapter(), NoopPlatformAdapter())
    return SeoService(session, "admin@example.com", workflow=workflow)


def test_low_risk_seo_auto_updates_shopify_and_records_snapshot() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        task = add_seo_task(
            session, product, fields=SEO_LOW_FIELDS, risk_level="low"
        )
        adapter = RecordingPlatformAdapter()

        result = make_service(session).run(task, adapter)
        session.commit()

        assert result is TaskState.PUBLISHED
        assert adapter.write_calls[0][0] == "update_product"
        written = adapter.write_calls[0][2]
        assert written.title == "Classic T-Shirt"
        assert written.meta_title == "Optimized Meta Title"
        assert written.meta_description == "Optimized meta description"
        assert written.alt_text == {"front.jpg": "Optimized alt text"}
        assert written.tags == ["optimized", "summer"]

        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.meta_title == "Optimized Meta Title"
        assert refreshed.meta_description == "Optimized meta description"
        assert refreshed.alt_text == {"front.jpg": "Optimized alt text"}
        assert refreshed.tags == ["optimized", "summer"]

        assert refreshed.status == ProductStatus.ACTIVE.value
        assert session.get(Task, task.id).status == TaskState.PUBLISHED.value

        snapshot = session.scalar(select(ProductSnapshot))
        assert snapshot is not None
        assert snapshot.kind == SnapshotKind.PUBLISH.value
        assert snapshot.version == 1
        assert snapshot.field_diff["meta_title"] == {
            "from": "Old Meta Title",
            "to": "Optimized Meta Title",
        }

        draft = session.scalar(
            select(ProductDraft).where(ProductDraft.task_id == task.id)
        )
        assert draft is not None
        assert draft.status == DraftStatus.PUBLISHED.value


def test_low_risk_seo_write_failure_marks_task_failed_and_keeps_suggestion() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        task = add_seo_task(
            session, product, fields=SEO_LOW_FIELDS, risk_level="low"
        )
        adapter = RecordingPlatformAdapter(
            receipts=[PlatformReceipt.failed("storefront rejected the write")]
        )

        result = make_service(session).run(task, adapter)
        session.commit()

        assert result is TaskState.FAILED
        assert session.scalar(select(ProductSnapshot)) is None
        refreshed_task = session.get(Task, task.id)
        assert refreshed_task is not None
        assert refreshed_task.status == TaskState.FAILED.value
        assert "storefront" in (refreshed_task.last_error or "")
        assert session.get(Product, product.id).meta_title == "Old Meta Title"

        draft = session.scalar(
            select(ProductDraft).where(ProductDraft.task_id == task.id)
        )
        assert draft is not None
        assert draft.status == DraftStatus.PENDING_REVIEW.value


def test_medium_risk_seo_queues_a_draft_without_writing() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        task = add_seo_task(
            session, product, fields=SEO_WITH_TITLE_FIELDS, risk_level="medium"
        )
        adapter = RecordingPlatformAdapter()

        result = make_service(session).run(task, adapter)
        session.commit()

        assert result is TaskState.AWAITING_REVIEW
        assert adapter.write_calls == []

        draft = session.scalar(
            select(ProductDraft).where(ProductDraft.task_id == task.id)
        )
        assert draft is not None
        assert draft.status == DraftStatus.PENDING_REVIEW.value
        assert draft.title == "Optimized Classic T-Shirt"
        assert draft.meta_title == "Optimized Meta Title"
        assert draft.alt_text == {"front.jpg": "Optimized alt text"}
        assert session.get(Task, task.id).status == TaskState.AWAITING_REVIEW.value


def test_seo_rejects_a_product_that_is_not_published() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        product.status = ProductStatus.DRAFT.value
        product.shopify_product_id = None
        task = add_seo_task(
            session, product, fields=SEO_LOW_FIELDS, risk_level="low"
        )
        adapter = RecordingPlatformAdapter()

        with pytest.raises(SeoProductNotPublished):
            make_service(session).run(task, adapter)

        assert adapter.write_calls == []


def test_seo_change_is_rollbackable_to_the_previous_version() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        task = add_seo_task(
            session, product, fields=SEO_LOW_FIELDS, risk_level="low"
        )
        adapter = RecordingPlatformAdapter()
        make_service(session).run(task, adapter)
        session.commit()

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = session.get(Product, product.id)
        assert product is not None
        rollback_adapter = RecordingPlatformAdapter()
        result = PublishService(
            session, "admin@example.com", rollback_adapter
        ).rollback(product.id, version=1)
        session.commit()

        assert rollback_adapter.write_calls[0][0] == "update_product"
        assert result.snapshot.kind == SnapshotKind.ROLLBACK.value
        assert result.snapshot.restored_version == 1
        assert result.product.meta_title == "Old Meta Title"
        assert result.product.meta_description == "Old meta description"
        assert result.product.alt_text == {"front.jpg": "Old alt"}
        assert result.task is not None
        assert result.task.status == TaskState.ROLLED_BACK.value


def test_run_task_workflow_auto_updates_low_risk_seo() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_published_product(session)
        task = TaskService(session, actor="admin@example.com").create(
            TaskCreate(
                kind=TaskKind.SEO,
                operation_type=OperationType.UPDATE,
                changed_fields=SEO_LOW_FIELDS,
                product_id=product.id,
            )
        )
        session.commit()
        task_id = task.id

    adapter = RecordingPlatformAdapter()

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        status = run_task_workflow(
            session, task_id, adapter_factory=lambda tenant_id: adapter
        )
        session.commit()

        assert status == TaskState.PUBLISHED.value
        assert adapter.write_calls[0][0] == "update_product"
        written = adapter.write_calls[0][2]
        assert written.alt_text == {"front.jpg": "Classic T-Shirt Apparel"}
        assert written.tags == ["Apparel", "cotton", "summer"]
        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.alt_text == {"front.jpg": "Classic T-Shirt Apparel"}
        assert session.get(Task, task_id).status == TaskState.PUBLISHED.value
