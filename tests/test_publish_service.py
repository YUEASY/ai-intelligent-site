from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.domain.snapshot import SnapshotKind
from app.domain.task_state import TaskState
from app.models import Product, ProductDraft, ProductSnapshot, ProductVariant, Task
from app.platform import PlatformReceipt, RecordingPlatformAdapter
from app.publish_service import (
    DraftNotPublishable,
    PublishConfirmationRequired,
    PublishFailed,
    PublishService,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_product(session: TenantSession) -> Product:
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
        meta_title="Classic Cotton T-Shirt",
        meta_description="Shop our classic cotton T-shirt",
        handle="classic-t-shirt",
        status="draft",
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


def add_task(
    session: TenantSession, product: Product, *, status: str
) -> Task:
    task = Task(
        tenant_id=session.tenant_id,
        kind="product",
        operation_type="update",
        changed_fields=["title", "description"],
        risk_level="medium",
        status=status,
        product_id=product.id,
    )
    session.add(task)
    session.flush()
    return task


def add_draft(
    session: TenantSession, task: Task, product: Product, *, status: str
) -> ProductDraft:
    draft = ProductDraft(
        tenant_id=session.tenant_id,
        product_id=product.id,
        task_id=task.id,
        title="Edited Classic T-Shirt",
        description="Edited heavy cotton tee",
        meta_title="Edited meta title",
        meta_description="Edited meta description",
        alt_text={},
        seo_tags=["edited", "cotton"],
        risk_level="medium",
        status=status,
    )
    session.add(draft)
    session.flush()
    return draft


def test_publish_requires_confirmation() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        task = add_task(
            session, product, status=TaskState.AWAITING_REVIEW.value
        )
        draft = add_draft(
            session, task, product, status=DraftStatus.PENDING_REVIEW.value
        )
        service = PublishService(
            session, "admin@example.com", RecordingPlatformAdapter()
        )

        with pytest.raises(PublishConfirmationRequired):
            service.publish(draft.id, confirmed=False)


def test_publish_writes_snapshot_and_marks_published() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        task = add_task(
            session, product, status=TaskState.AWAITING_REVIEW.value
        )
        draft = add_draft(
            session, task, product, status=DraftStatus.PENDING_REVIEW.value
        )
        adapter = RecordingPlatformAdapter()
        result = PublishService(
            session, "admin@example.com", adapter
        ).publish(draft.id, confirmed=True)
        session.commit()

        assert result.remote_id == "remote-1"
        assert adapter.write_calls[0][0] == "publish_product"
        assert result.draft.status == DraftStatus.PUBLISHED.value
        assert result.task.status == TaskState.PUBLISHED.value
        assert result.snapshot.version == 1
        assert result.snapshot.kind == SnapshotKind.PUBLISH.value
        assert result.snapshot.field_diff["title"] == {
            "from": "Classic T-Shirt",
            "to": "Edited Classic T-Shirt",
        }
        assert result.snapshot.field_diff["status"] == {
            "from": "draft",
            "to": "active",
        }

        refreshed = session.get(Product, product.id)
        assert refreshed is not None
        assert refreshed.title == "Edited Classic T-Shirt"
        assert refreshed.status == "active"
        assert refreshed.shopify_product_id == "remote-1"


def test_publish_failure_keeps_local_state_unchanged() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        task = add_task(
            session, product, status=TaskState.AWAITING_REVIEW.value
        )
        draft = add_draft(
            session, task, product, status=DraftStatus.PENDING_REVIEW.value
        )
        adapter = RecordingPlatformAdapter(
            receipts=[PlatformReceipt.failed("storefront rejected the write")]
        )

        with pytest.raises(PublishFailed):
            PublishService(session, "admin@example.com", adapter).publish(
                draft.id, confirmed=True
            )

        assert task.status == TaskState.APPROVED.value
        assert draft.status == DraftStatus.APPROVED.value
        assert product.title == "Classic T-Shirt"
        assert product.status == "draft"
        assert product.shopify_product_id is None
        assert session.scalar(select(ProductSnapshot)) is None


def test_second_publish_updates_existing_shopify_product() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        product.shopify_product_id = "shopify-123"
        task = add_task(session, product, status=TaskState.APPROVED.value)
        draft = add_draft(session, task, product, status=DraftStatus.APPROVED.value)
        adapter = RecordingPlatformAdapter()

        result = PublishService(
            session, "admin@example.com", adapter
        ).publish(draft.id, confirmed=True)
        session.commit()

        assert adapter.write_calls[0][0] == "update_product"
        assert result.snapshot.version == 1


def test_publish_rejects_a_non_reviewable_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        task = add_task(session, product, status=TaskState.PUBLISHED.value)
        draft = add_draft(session, task, product, status=DraftStatus.PUBLISHED.value)

        service = PublishService(
            session, "admin@example.com", RecordingPlatformAdapter()
        )
        with pytest.raises(DraftNotPublishable):
            service.publish(draft.id, confirmed=True)


def test_rollback_restores_previous_version_and_rolls_back_task() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = add_product(session)
        task = add_task(
            session, product, status=TaskState.AWAITING_REVIEW.value
        )
        draft = add_draft(
            session, task, product, status=DraftStatus.PENDING_REVIEW.value
        )
        adapter = RecordingPlatformAdapter()
        service = PublishService(session, "admin@example.com", adapter)

        service.publish(draft.id, confirmed=True)
        session.commit()

        with TenantSession(
            bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
        ) as rollback_session:
            rollback_adapter = RecordingPlatformAdapter()
            result = PublishService(
                rollback_session, "admin@example.com", rollback_adapter
            ).rollback(product.id, version=1)
            rollback_session.commit()

            assert rollback_adapter.write_calls[0][0] == "update_product"
            assert result.snapshot.kind == SnapshotKind.ROLLBACK.value
            assert result.snapshot.restored_version == 1
            assert result.task is not None
            assert result.task.status == TaskState.ROLLED_BACK.value
            assert result.product.title == "Classic T-Shirt"
            assert result.product.status == "draft"

            rolled_draft = rollback_session.scalar(
                select(ProductDraft).where(ProductDraft.task_id == task.id)
            )
            assert rolled_draft is not None
            assert rolled_draft.status == DraftStatus.ROLLED_BACK.value
