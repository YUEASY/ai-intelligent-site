from uuid import UUID

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.domain.risk import ProductField
from app.domain.task_state import TaskState
from app.generation.model_adapter import GeneratedContent, ModelTier
from app.generation.workflow import ProductWorkflow
from app.models import Page, PageDraft, PageSnapshot, Task
from app.page_publish_service import PagePublishService
from app.page_seo_service import (
    PAGE_SEO_ALL_FIELDS,
    PAGE_SEO_LOW_RISK_FIELDS,
    PageSeoService,
)
from app.platform import NoopPlatformAdapter, RecordingPlatformAdapter
from app.schemas import TaskKind

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakePageSeoModel:
    def generate(
        self, tier: ModelTier, product: object, fields: frozenset[ProductField]
    ) -> GeneratedContent:
        del tier, product
        return GeneratedContent(
            title="About Our Studio" if ProductField.TITLE in fields else None,
            meta_title="About Our Sustainable Studio"
            if ProductField.META_TITLE in fields
            else None,
            meta_description="Learn how our studio makes durable goods."
            if ProductField.META_DESCRIPTION in fields
            else None,
            seo_tags=["studio", "sustainable"]
            if ProductField.SEO_TAGS in fields
            else None,
        )


def setup() -> tuple[Engine, UUID]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with TenantSession(
        bind=engine, tenant_id=TENANT_ID, expire_on_commit=False
    ) as session:
        page = Page(
            tenant_id=TENANT_ID,
            title="About",
            body_html="Our story",
            handle="about",
            meta_title="About",
            meta_description="Old",
            seo_tags=["company"],
            status="active",
            shopify_page_id="42",
        )
        session.add(page)
        session.commit()
        return engine, page.id


def run_page(engine: Engine, page_id: UUID, fields: set[ProductField], risk: str):
    adapter = RecordingPlatformAdapter()
    with TenantSession(
        bind=engine, tenant_id=TENANT_ID, expire_on_commit=False
    ) as session:
        task = Task(
            tenant_id=TENANT_ID,
            kind=TaskKind.SEO.value,
            operation_type="update",
            changed_fields=sorted(field.value for field in fields),
            risk_level=risk,
            status=TaskState.RUNNING.value,
            page_id=page_id,
        )
        session.add(task)
        session.flush()
        workflow = ProductWorkflow(FakePageSeoModel(), NoopPlatformAdapter())
        result = PageSeoService(session, "admin@example.com", workflow).run(
            task, adapter
        )
        session.commit()
        return result, adapter, task.id


def test_low_risk_page_seo_writes_and_snapshots() -> None:
    engine, page_id = setup()
    result, adapter, task_id = run_page(
        engine, page_id, set(PAGE_SEO_LOW_RISK_FIELDS), "low"
    )
    assert result is TaskState.PUBLISHED
    assert adapter.write_calls[0][0] == "update_page"
    with TenantSession(bind=engine, tenant_id=TENANT_ID) as session:
        assert session.get(Page, page_id).meta_title == "About Our Sustainable Studio"
        assert session.get(Task, task_id).status == TaskState.PUBLISHED.value
        assert session.scalar(select(PageSnapshot)) is not None


def test_medium_risk_page_title_waits_for_review_without_write() -> None:
    engine, page_id = setup()
    result, adapter, task_id = run_page(
        engine, page_id, set(PAGE_SEO_ALL_FIELDS), "medium"
    )
    assert result is TaskState.AWAITING_REVIEW
    assert adapter.write_calls == []
    with TenantSession(bind=engine, tenant_id=TENANT_ID) as session:
        draft = session.scalar(select(PageDraft).where(PageDraft.task_id == task_id))
        assert draft is not None and draft.status == DraftStatus.PENDING_REVIEW.value


def test_page_seo_snapshot_rolls_back() -> None:
    engine, page_id = setup()
    run_page(engine, page_id, set(PAGE_SEO_LOW_RISK_FIELDS), "low")
    with TenantSession(
        bind=engine, tenant_id=TENANT_ID, expire_on_commit=False
    ) as session:
        page, _, snapshot = PagePublishService(
            session, "admin@example.com", RecordingPlatformAdapter()
        ).rollback(page_id, 1)
        session.commit()
        assert page.meta_title == "About"
        assert snapshot.restored_version == 1
