from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import RequestContext, get_request_context
from app.domain.task_state import InvalidTaskTransition
from app.schemas import AuditLogRead, TaskCreate, TaskRead, TaskTransitionRequest
from app.services import TaskNotFoundError, TaskService
from app.worker import execute_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _service(context: RequestContext) -> TaskService:
    return TaskService(context.session, actor=context.actor)


@router.post("", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
def create_task(
    command: TaskCreate,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    task = _service(context).create(command)
    context.session.commit()
    execute_task.delay(str(task.id), str(task.tenant_id))
    return TaskRead.model_validate(task)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[TaskRead]:
    return [TaskRead.model_validate(task) for task in _service(context).list_tasks()]


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        task = _service(context).get(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return TaskRead.model_validate(task)


@router.post("/{task_id}/transitions", response_model=TaskRead)
def transition_task(
    task_id: UUID,
    command: TaskTransitionRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        task = _service(context).advance(task_id, command.target)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskRead.model_validate(task)


@router.get("/{task_id}/audit-log", response_model=list[AuditLogRead])
def get_task_audit_log(
    task_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[AuditLogRead]:
    try:
        entries = _service(context).audit_log(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return [AuditLogRead.model_validate(entry) for entry in entries]
