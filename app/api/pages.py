from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.platform_deps import PlatformAdapterFactory, get_platform_adapter_factory
from app.dependencies import RequestContext, get_request_context
from app.domain.risk import OperationType
from app.models import PageSnapshot
from app.page_publish_service import PagePublishService
from app.page_seo_service import PAGE_SEO_ALL_FIELDS, PAGE_SEO_LOW_RISK_FIELDS
from app.page_service import PageNotFoundError, PageService
from app.publish_service import PublishFailed
from app.schemas import (
    PageRead,
    PageRollbackRead,
    PageSnapshotRead,
    RollbackRequest,
    SeoRequest,
    TaskCreate,
    TaskKind,
    TaskRead,
)
from app.services import TaskService
from app.worker import execute_task

router = APIRouter(prefix="/pages", tags=["pages"])


@router.get("", response_model=list[PageRead])
def list_pages(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[PageRead]:
    return [
        PageRead.model_validate(page)
        for page in PageService(context.session).list_pages()
    ]


@router.post(
    "/{page_id}/seo", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED
)
def optimize_page_seo(
    page_id: UUID,
    command: SeoRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        page = PageService(context.session).get(page_id)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Page not found") from exc
    if page.status != "active" or not page.shopify_page_id:
        raise HTTPException(status_code=409, detail="Page is not published yet")
    fields = PAGE_SEO_ALL_FIELDS if command.include_title else PAGE_SEO_LOW_RISK_FIELDS
    task = TaskService(context.session, context.actor).create(
        TaskCreate(
            kind=TaskKind.SEO,
            operation_type=OperationType.UPDATE,
            changed_fields=set(fields),
            page_id=page_id,
        )
    )
    context.session.commit()
    execute_task.delay(str(task.id), str(task.tenant_id))
    return TaskRead.model_validate(task)


@router.get("/{page_id}/versions", response_model=list[PageSnapshotRead])
def list_page_versions(
    page_id: UUID, context: Annotated[RequestContext, Depends(get_request_context)]
) -> list[PageSnapshotRead]:
    PageService(context.session).get(page_id)
    snapshots = context.session.scalars(
        select(PageSnapshot)
        .where(PageSnapshot.page_id == page_id)
        .order_by(PageSnapshot.version.desc())
    )
    return [PageSnapshotRead.model_validate(item) for item in snapshots]


@router.post("/{page_id}/rollback", response_model=PageRollbackRead)
def rollback_page(
    page_id: UUID,
    command: RollbackRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
    adapter_factory: Annotated[
        PlatformAdapterFactory, Depends(get_platform_adapter_factory)
    ],
) -> PageRollbackRead:
    try:
        page, task, snapshot = PagePublishService(
            context.session, context.actor, adapter_factory(context.tenant_id)
        ).rollback(page_id, command.version)
    except (PageNotFoundError, LookupError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PublishFailed as exc:
        raise HTTPException(
            status_code=502, detail="Shopify did not confirm the rollback"
        ) from exc
    context.session.commit()
    return PageRollbackRead(
        page=PageRead.model_validate(page),
        task=TaskRead.model_validate(task) if task else None,
        snapshot=PageSnapshotRead.model_validate(snapshot),
    )
