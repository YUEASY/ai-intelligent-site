from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import func, select

from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.snapshot import SnapshotKind, diff_states
from app.domain.task_state import TaskState
from app.models import Page, PageDraft, PageSnapshot, Task
from app.page_seo_service import canonical_page, page_state
from app.page_service import PageService
from app.platform import PlatformAdapter
from app.publish_service import (
    DraftNotPublishable,
    PublishConfirmationRequired,
    PublishFailed,
)
from app.services import TaskService


@dataclass(frozen=True)
class PagePublishResult:
    draft: PageDraft
    task: Task
    snapshot: PageSnapshot
    remote_id: str


class PagePublishService:
    def __init__(
        self, session: TenantSession, actor: str, adapter: PlatformAdapter
    ) -> None:
        self._session, self._actor, self._adapter = session, actor, adapter

    def publish(self, draft: PageDraft, *, confirmed: bool) -> PagePublishResult:
        if not confirmed:
            raise PublishConfirmationRequired(
                "Publishing is high-risk and requires explicit confirmation"
            )
        if draft.status != DraftStatus.APPROVED.value:
            raise DraftNotPublishable(f"Draft {draft.id} cannot be published")
        page = PageService(self._session).get(draft.page_id)
        before = page_state(page)
        after = {
            **before,
            "title": draft.title,
            "body_html": draft.body_html,
            "meta_title": draft.meta_title,
            "meta_description": draft.meta_description,
            "seo_tags": list(draft.seo_tags),
        }
        snapshot = self._capture(page, before, after, SnapshotKind.PUBLISH)
        receipt = self._adapter.update_page(page.tenant_id, canonical_page(page, after))
        if not receipt.success:
            self._session.delete(snapshot)
            raise PublishFailed(
                receipt.error or "Shopify did not confirm the page publish"
            )
        page.title, page.body_html = draft.title, draft.body_html
        page.meta_title, page.meta_description = (
            draft.meta_title,
            draft.meta_description,
        )
        page.seo_tags = list(draft.seo_tags)
        task = TaskService(self._session, self._actor).advance(
            draft.task_id, TaskState.PUBLISHED
        )
        draft.status = DraftStatus.PUBLISHED.value
        self._session.flush()
        return PagePublishResult(draft, task, snapshot, receipt.remote_id or "")

    def rollback(
        self, page_id: UUID, version: int
    ) -> tuple[Page, Task | None, PageSnapshot]:
        page = PageService(self._session).get(page_id)
        target = self._session.scalar(
            select(PageSnapshot).where(
                PageSnapshot.page_id == page_id, PageSnapshot.version == version
            )
        )
        if target is None:
            raise LookupError(f"Page snapshot version {version} not found")
        before, after = page_state(page), dict(target.payload)
        snapshot = self._capture(page, before, after, SnapshotKind.ROLLBACK, version)
        receipt = self._adapter.update_page(page.tenant_id, canonical_page(page, after))
        if not receipt.success:
            self._session.delete(snapshot)
            raise PublishFailed(
                receipt.error or "Shopify did not confirm the page rollback"
            )
        page.title, page.body_html, page.handle = (
            str(after["title"]),
            str(after["body_html"]),
            str(after["handle"]),
        )
        page.meta_title, page.meta_description = (
            str(after["meta_title"]),
            str(after["meta_description"]),
        )
        page.seo_tags = list(cast(list[str], after["seo_tags"]))
        task = self._session.scalar(
            select(Task)
            .where(Task.page_id == page_id, Task.status == TaskState.PUBLISHED.value)
            .order_by(Task.updated_at.desc())
            .limit(1)
        )
        if task:
            TaskService(self._session, self._actor).advance(
                task.id, TaskState.ROLLED_BACK
            )
        self._session.flush()
        return page, task, snapshot

    def _capture(
        self,
        page: Page,
        before: dict[str, object],
        after: dict[str, object],
        kind: SnapshotKind,
        restored_version: int | None = None,
    ) -> PageSnapshot:
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
            kind=kind.value,
            payload=before,
            field_diff=diff_states(before, after),
            actor=self._actor,
            restored_version=restored_version,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot
