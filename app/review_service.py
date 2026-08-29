"""Human review decisions for generated drafts.

Review actions operate on drafts whose owning task is ``awaiting_review`` and
advance that task through the state machine so every decision lands in the
audit log.  Regeneration is the one action that starts a fresh task instead.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.review import RejectionReason
from app.domain.risk import OperationType
from app.domain.task_state import TaskState
from app.generation.service import DraftNotFoundError
from app.generation.workflow import ALL_CONTENT_FIELDS
from app.models import ProductDraft, Task
from app.schemas import DraftEditRequest, TaskCreate, TaskKind
from app.services import TaskService


class DraftNotReviewable(ValueError):
    pass


class ReviewService:
    def __init__(self, session: TenantSession, actor: str) -> None:
        self._session = session
        self._actor = actor

    def approve(self, draft_ids: Collection[UUID]) -> list[ProductDraft]:
        drafts = self._reviewable_drafts(draft_ids)
        task_service = TaskService(self._session, self._actor)
        for draft in drafts:
            task_service.advance(draft.task_id, TaskState.APPROVED)
            draft.status = DraftStatus.APPROVED.value
        self._session.flush()
        return drafts

    def reject(
        self, draft_ids: Collection[UUID], reason: RejectionReason
    ) -> list[ProductDraft]:
        drafts = self._reviewable_drafts(draft_ids)
        task_service = TaskService(self._session, self._actor)
        for draft in drafts:
            task_service.advance(draft.task_id, TaskState.REJECTED)
            draft.status = DraftStatus.REJECTED.value
            draft.rejection_reason = reason.value
        self._session.flush()
        return drafts

    def edit(self, draft_id: UUID, edits: DraftEditRequest) -> ProductDraft:
        draft = self._get(draft_id)
        if draft.status != DraftStatus.PENDING_REVIEW.value:
            raise DraftNotReviewable(
                f"Draft {draft_id} is not awaiting review"
            )
        for field, value in edits.model_dump(exclude_none=True).items():
            setattr(draft, field, value)
        self._session.flush()
        return draft

    def regenerate(self, draft_id: UUID) -> Task:
        draft = self._get(draft_id)
        if draft.status not in {
            DraftStatus.PENDING_REVIEW.value,
            DraftStatus.REJECTED.value,
        }:
            raise DraftNotReviewable(
                f"Draft {draft_id} cannot be regenerated"
            )
        task_service = TaskService(self._session, self._actor)
        if draft.status == DraftStatus.PENDING_REVIEW.value:
            task_service.advance(draft.task_id, TaskState.REJECTED)
            draft.status = DraftStatus.REJECTED.value
            draft.rejection_reason = RejectionReason.OTHER.value
        task = task_service.create(
            TaskCreate(
                kind=TaskKind.PRODUCT,
                operation_type=OperationType.UPDATE,
                changed_fields=set(ALL_CONTENT_FIELDS),
                product_id=draft.product_id,
            )
        )
        self._session.flush()
        return task

    def _reviewable_drafts(
        self, draft_ids: Collection[UUID]
    ) -> list[ProductDraft]:
        ids = list(draft_ids)
        drafts = list(
            self._session.scalars(
                select(ProductDraft).where(ProductDraft.id.in_(ids))
            )
        )
        found = {draft.id for draft in drafts}
        missing = [str(draft_id) for draft_id in ids if draft_id not in found]
        if missing:
            raise DraftNotFoundError(", ".join(missing))
        not_reviewable = [
            str(draft.id)
            for draft in drafts
            if draft.status != DraftStatus.PENDING_REVIEW.value
        ]
        if not_reviewable:
            raise DraftNotReviewable(
                "Drafts not awaiting review: " + ", ".join(not_reviewable)
            )
        return drafts

    def _get(self, draft_id: UUID) -> ProductDraft:
        draft = self._session.scalar(
            select(ProductDraft).where(ProductDraft.id == draft_id)
        )
        if draft is None:
            raise DraftNotFoundError(str(draft_id))
        return draft
