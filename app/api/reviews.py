from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.platform_deps import (
    PlatformAdapterFactory,
    get_platform_adapter_factory,
)
from app.dependencies import RequestContext, get_request_context
from app.generation.service import DraftNotFoundError, DraftService
from app.publish_service import (
    DraftNotPublishable,
    PublishConfirmationRequired,
    PublishFailed,
    PublishService,
)
from app.review_service import DraftNotReviewable, ReviewService
from app.schemas import (
    DraftEditRequest,
    DraftRead,
    PublishRead,
    PublishRequest,
    RejectRequest,
    ReviewActionRequest,
    SnapshotRead,
    TaskRead,
)
from app.shopify.products import NoConnectedShopifyStore
from app.worker import execute_task

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/queue", response_model=list[DraftRead])
def review_queue(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[DraftRead]:
    return [
        DraftRead.model_validate(draft)
        for draft in DraftService(context.session).review_queue()
    ]


@router.post("/approve", response_model=list[DraftRead])
def approve_reviews(
    command: ReviewActionRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[DraftRead]:
    try:
        drafts = ReviewService(context.session, context.actor).approve(
            command.draft_ids
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotReviewable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    context.session.commit()
    return [DraftRead.model_validate(draft) for draft in drafts]


@router.post("/reject", response_model=list[DraftRead])
def reject_reviews(
    command: RejectRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[DraftRead]:
    try:
        drafts = ReviewService(context.session, context.actor).reject(
            command.draft_ids, command.reason
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotReviewable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    context.session.commit()
    return [DraftRead.model_validate(draft) for draft in drafts]


@router.patch("/{draft_id}", response_model=DraftRead)
def edit_draft(
    draft_id: UUID,
    command: DraftEditRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> DraftRead:
    try:
        draft = ReviewService(context.session, context.actor).edit(
            draft_id, command
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotReviewable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    context.session.commit()
    return DraftRead.model_validate(draft)


@router.post(
    "/{draft_id}/regenerate",
    response_model=TaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_draft(
    draft_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        task = ReviewService(context.session, context.actor).regenerate(draft_id)
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context.session.commit()
    execute_task.delay(str(task.id), str(task.tenant_id))
    return TaskRead.model_validate(task)


@router.post("/{draft_id}/publish", response_model=PublishRead)
def publish_draft(
    draft_id: UUID,
    command: PublishRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
    adapter_factory: Annotated[
        PlatformAdapterFactory, Depends(get_platform_adapter_factory)
    ],
) -> PublishRead:
    try:
        adapter = adapter_factory(context.tenant_id)
    except NoConnectedShopifyStore as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shopify store is not connected",
        ) from exc
    try:
        result = PublishService(context.session, context.actor, adapter).publish(
            draft_id, confirmed=command.confirmed
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotPublishable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublishConfirmationRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublishFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shopify did not confirm the publish",
        ) from exc
    context.session.commit()
    return PublishRead(
        draft=DraftRead.model_validate(result.draft),
        task=TaskRead.model_validate(result.task),
        snapshot=SnapshotRead.model_validate(result.snapshot),
        remote_id=result.remote_id,
    )
