from uuid import UUID

from celery import Task as CeleryTask  # type: ignore[import-untyped]
from sqlalchemy.exc import OperationalError

from app.celery_app import celery_app
from app.database import TenantSession, tenant_session_scope
from app.domain.risk import RiskLevel
from app.domain.task_state import InvalidTaskTransition, TaskState
from app.generation.service import GenerationService
from app.generation.workflow import GenerationError
from app.product_service import ProductNotFoundError
from app.services import TaskNotFoundError, TaskService, completion_state
from app.shopify.types import WebhookEventStatus
from app.shopify.webhook_service import ShopifyWebhookService, WebhookEventNotFound


class RecoverableTaskError(RuntimeError):
    """An adapter failure that is safe to retry without changing input."""


class DeterministicTaskError(RuntimeError):
    """A validation or parameter failure that retrying cannot fix."""


def run_task_workflow(session: TenantSession, task_id: UUID) -> str:
    """Advance a task through its workflow, generating content when applicable.

    Generation never writes to the storefront; it only produces a draft.
    """

    service = TaskService(session, actor="system:celery")
    task = service.get(task_id, for_update=True)
    current = TaskState(task.status)
    if current is TaskState.PENDING:
        service.advance(task_id, TaskState.RUNNING)
        session.commit()
    elif current is not TaskState.RUNNING:
        return current.value

    if task.product_id is not None:
        try:
            GenerationService(session).generate(task)
        except (GenerationError, ProductNotFoundError) as exc:
            service.fail(task_id, str(exc))
            return TaskState.FAILED.value

    target = completion_state(RiskLevel(task.risk_level))
    return service.advance(task_id, target).status


def _run_workflow(task_id: UUID, tenant_id: UUID) -> str:
    with tenant_session_scope(tenant_id) as session:
        return run_task_workflow(session, task_id)


def _mark_failed(task_id: UUID, tenant_id: UUID, error: Exception) -> None:
    with tenant_session_scope(tenant_id) as session:
        service = TaskService(session, actor="system:celery")
        try:
            task = service.get(task_id, for_update=True)
            if TaskState(task.status) is TaskState.PENDING:
                service.advance(task_id, TaskState.RUNNING)
            service.fail(task_id, str(error))
        except (InvalidTaskTransition, TaskNotFoundError):
            return


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, max_retries=3, name="tasks.execute"
)
def execute_task(self: CeleryTask, task_id: str, tenant_id: str) -> str:
    try:
        parsed_task_id = UUID(task_id)
        parsed_tenant_id = UUID(tenant_id)
        return _run_workflow(parsed_task_id, parsed_tenant_id)
    except (ValueError, DeterministicTaskError) as exc:
        try:
            parsed_task_id = UUID(task_id)
            parsed_tenant_id = UUID(tenant_id)
        except ValueError:
            return TaskState.FAILED.value
        _mark_failed(parsed_task_id, parsed_tenant_id, exc)
        return TaskState.FAILED.value
    except (
        RecoverableTaskError,
        OperationalError,
        ConnectionError,
        TimeoutError,
    ) as exc:
        parsed_task_id = UUID(task_id)
        parsed_tenant_id = UUID(tenant_id)
        if self.request.retries >= 3:
            _mark_failed(parsed_task_id, parsed_tenant_id, exc)
            return TaskState.FAILED.value
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@celery_app.task(name="shopify.webhooks.process")  # type: ignore[untyped-decorator]
def process_shopify_webhook(event_id: str, tenant_id: str) -> str:
    try:
        parsed_event_id = UUID(event_id)
        parsed_tenant_id = UUID(tenant_id)
    except ValueError:
        return WebhookEventStatus.DEAD_LETTER.value

    try:
        with tenant_session_scope(parsed_tenant_id) as session:
            return ShopifyWebhookService(session).process(parsed_event_id)
    except Exception as exc:
        with tenant_session_scope(parsed_tenant_id) as session:
            try:
                ShopifyWebhookService(session).mark_dead_letter(
                    parsed_event_id,
                    f"Webhook processing failed: {type(exc).__name__}: {exc}",
                )
            except WebhookEventNotFound:
                return WebhookEventStatus.DEAD_LETTER.value
        return WebhookEventStatus.DEAD_LETTER.value
