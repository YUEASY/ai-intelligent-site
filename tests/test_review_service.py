from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.domain.review import RejectionReason
from app.domain.task_state import TaskState
from app.models import Product, ProductDraft, ProductVariant, Task
from app.review_service import DraftNotReviewable, ReviewService
from app.schemas import DraftEditRequest

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_fixtures(session: TenantSession) -> tuple[Product, Task, ProductDraft]:
    product = Product(
        tenant_id=session.tenant_id,
        source="merchant_csv",
        source_id="product-1",
        sku="TSHIRT",
        title="Classic T-Shirt",
        description="Heavy cotton tee",
        category="Apparel",
        tags=["summer"],
        images=["front.jpg"],
        meta_title="Classic T-Shirt",
        meta_description="Shop our tee",
        handle="classic-t-shirt",
        status="draft",
        variants=[
            ProductVariant(
                tenant_id=session.tenant_id,
                sku="TSHIRT-BLK",
                options={"Color": "Black"},
                price=Decimal("29.90"),
                cost=None,
                inventory=5,
                image=None,
            )
        ],
    )
    session.add(product)
    session.flush()
    task = Task(
        tenant_id=session.tenant_id,
        kind="product",
        operation_type="update",
        changed_fields=["title"],
        risk_level="medium",
        status=TaskState.AWAITING_REVIEW.value,
        product_id=product.id,
    )
    session.add(task)
    session.flush()
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
        risk_level="medium",
        status=DraftStatus.PENDING_REVIEW.value,
    )
    session.add(draft)
    session.flush()
    return product, task, draft


def test_approve_advances_task_and_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        _, task, draft = add_fixtures(session)

        drafts = ReviewService(session, "admin@example.com").approve([draft.id])
        session.commit()

        assert drafts[0].status == DraftStatus.APPROVED.value
        assert task.status == TaskState.APPROVED.value


def test_reject_records_structured_reason() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        _, task, draft = add_fixtures(session)

        drafts = ReviewService(session, "admin@example.com").reject(
            [draft.id], RejectionReason.FACT_ERROR
        )
        session.commit()

        assert drafts[0].status == DraftStatus.REJECTED.value
        assert drafts[0].rejection_reason == RejectionReason.FACT_ERROR.value
        assert task.status == TaskState.REJECTED.value


def test_edit_updates_content_fields_on_a_pending_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        _, _, draft = add_fixtures(session)

        edited = ReviewService(session, "admin@example.com").edit(
            draft.id,
            DraftEditRequest(title="Fixed Title", seo_tags=["fixed"]),
        )
        session.commit()

        assert edited.title == "Fixed Title"
        assert edited.seo_tags == ["fixed"]
        assert edited.status == DraftStatus.PENDING_REVIEW.value


def test_review_rejects_a_non_pending_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        _, task, draft = add_fixtures(session)
        ReviewService(session, "admin@example.com").approve([draft.id])

        with pytest.raises(DraftNotReviewable):
            ReviewService(session, "admin@example.com").reject(
                [draft.id], RejectionReason.OTHER
            )
        assert task.status == TaskState.APPROVED.value


def test_regenerate_creates_a_new_task_for_the_same_product() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product, task, draft = add_fixtures(session)

        new_task = ReviewService(session, "admin@example.com").regenerate(
            draft.id
        )
        session.commit()

        assert new_task.id != task.id
        assert new_task.product_id == product.id
        assert new_task.status == TaskState.PENDING.value
        assert new_task.risk_level == "medium"
        assert task.status == TaskState.REJECTED.value
        assert draft.status == DraftStatus.REJECTED.value
        assert draft.rejection_reason == RejectionReason.OTHER.value
        assert session.scalar(select(Task)) is not None


def test_regenerate_rejects_an_already_published_draft() -> None:
    engine = make_engine()
    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        _, task, draft = add_fixtures(session)
        task.status = TaskState.PUBLISHED.value
        draft.status = DraftStatus.PUBLISHED.value

        with pytest.raises(DraftNotReviewable):
            ReviewService(session, "admin@example.com").regenerate(draft.id)
