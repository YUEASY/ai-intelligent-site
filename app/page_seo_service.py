from decimal import Decimal
from typing import cast

from sqlalchemy import func, select

from app.cost_service import CostService
from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.page import CanonicalPage
from app.domain.product import CanonicalProduct, CanonicalVariant, ProductStatus
from app.domain.risk import ProductField, RiskLevel
from app.domain.snapshot import SnapshotKind, diff_states
from app.domain.task_state import TaskState
from app.generation.workflow import (
    GenerationError,
    ProductWorkflow,
    build_default_workflow,
)
from app.models import Page, PageDraft, PageSnapshot, Task
from app.page_service import PageService
from app.platform import PlatformAdapter
from app.services import TaskService

PAGE_SEO_LOW_RISK_FIELDS = frozenset(
    {ProductField.META_TITLE, ProductField.META_DESCRIPTION, ProductField.SEO_TAGS}
)
PAGE_SEO_ALL_FIELDS = PAGE_SEO_LOW_RISK_FIELDS | {ProductField.TITLE}


def page_state(page: Page) -> dict[str, object]:
    return {
        "title": page.title,
        "body_html": page.body_html,
        "handle": page.handle,
        "meta_title": page.meta_title,
        "meta_description": page.meta_description,
        "seo_tags": list(page.seo_tags),
        "status": page.status,
    }


def canonical_page(page: Page, state: dict[str, object]) -> CanonicalPage:
    return CanonicalPage(
        page.tenant_id,
        str(state["title"]),
        str(state["body_html"]),
        str(state["handle"]),
        str(state["meta_title"]),
        str(state["meta_description"]),
        list(cast(list[str], state["seo_tags"])),
        page.shopify_page_id,
    )


class PageSeoService:
    def __init__(
        self,
        session: TenantSession,
        actor: str,
        workflow: ProductWorkflow | None = None,
    ) -> None:
        self._session, self._actor = session, actor
        self._workflow = workflow or build_default_workflow()

    def run(self, task: Task, adapter: PlatformAdapter) -> TaskState:
        if task.page_id is None:
            raise ValueError("SEO task has no page to optimize")
        page = PageService(self._session).get(task.page_id)
        if page.status != "active" or not page.shopify_page_id:
            raise ValueError(f"Page {page.id} is not published yet")
        pseudo = CanonicalProduct(
            tenant_id=page.tenant_id,
            source="shopify_page",
            source_id=page.shopify_page_id,
            sku=f"page-{page.id}",
            title=page.title,
            description=page.body_html,
            category="page",
            tags=list(page.seo_tags),
            images=[],
            meta_title=page.meta_title,
            meta_description=page.meta_description,
            alt_text={},
            handle=page.handle,
            status=ProductStatus.ACTIVE,
            shopify_product_id=page.shopify_page_id,
            variants=[
                CanonicalVariant(
                    sku=f"page-{page.id}", options={}, price=Decimal(0), inventory=0
                )
            ],
        )
        fields = [ProductField(field) for field in task.changed_fields]
        try:
            generated = self._workflow.generate(pseudo, fields)
        except GenerationError as exc:
            if exc.usages:
                CostService(self._session).record(task.id, exc.usages)
            raise
        CostService(self._session).record(task.id, generated.usages)
        content = generated.content
        draft = PageDraft(
            tenant_id=page.tenant_id,
            page_id=page.id,
            task_id=task.id,
            title=content.title or page.title,
            body_html=page.body_html,
            meta_title=content.meta_title or page.meta_title,
            meta_description=content.meta_description or page.meta_description,
            seo_tags=content.seo_tags or list(page.seo_tags),
            risk_level=task.risk_level,
            status=DraftStatus.PENDING_REVIEW.value,
        )
        self._session.add(draft)
        self._session.flush()
        if RiskLevel(task.risk_level) is not RiskLevel.LOW:
            TaskService(self._session, self._actor).advance(
                task.id, TaskState.AWAITING_REVIEW
            )
            return TaskState.AWAITING_REVIEW
        TaskService(self._session, self._actor).advance(task.id, TaskState.SUGGESTED)
        self._session.commit()
        before = page_state(page)
        after = {
            **before,
            "title": draft.title,
            "meta_title": draft.meta_title,
            "meta_description": draft.meta_description,
            "seo_tags": draft.seo_tags,
        }
        version = (
            self._session.scalar(
                select(func.max(PageSnapshot.version)).where(
                    PageSnapshot.page_id == page.id
                )
            )
            or 0
        ) + 1
        snapshot = PageSnapshot(
            tenant_id=page.tenant_id,
            page_id=page.id,
            version=version,
            kind=SnapshotKind.PUBLISH.value,
            payload=before,
            field_diff=diff_states(before, after),
            actor=self._actor,
        )
        self._session.add(snapshot)
        receipt = adapter.update_page(page.tenant_id, canonical_page(page, after))
        if not receipt.success:
            self._session.delete(snapshot)
            TaskService(self._session, self._actor).fail(
                task.id, receipt.error or "Shopify did not confirm the page SEO update"
            )
            return TaskState.FAILED
        page.meta_title, page.meta_description, page.seo_tags = (
            draft.meta_title,
            draft.meta_description,
            draft.seo_tags,
        )
        draft.status = DraftStatus.PUBLISHED.value
        TaskService(self._session, self._actor).advance(task.id, TaskState.PUBLISHED)
        return TaskState.PUBLISHED
