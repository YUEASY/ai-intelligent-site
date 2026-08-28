from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.risk import RiskLevel, grade_risk
from app.domain.task_state import TaskState, transition
from app.models import Task, TaskAuditLog
from app.schemas import TaskCreate


class TaskNotFoundError(LookupError):
    pass


class TaskService:
    def __init__(self, session: TenantSession, actor: str) -> None:
        self.session = session
        self.actor = actor

    def create(self, command: TaskCreate) -> Task:
        risk_level = grade_risk(command.operation_type, command.changed_fields)
        task = Task(
            tenant_id=self.session.tenant_id,
            kind=command.kind.value,
            operation_type=command.operation_type.value,
            changed_fields=sorted(field.value for field in command.changed_fields),
            risk_level=risk_level.value,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def list_tasks(self) -> list[Task]:
        statement = select(Task).order_by(Task.created_at.desc())
        return list(self.session.scalars(statement))

    def get(self, task_id: UUID, *, for_update: bool = False) -> Task:
        statement = select(Task).where(Task.id == task_id)
        if for_update:
            statement = statement.with_for_update()
        task = self.session.scalar(statement)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    def advance(self, task_id: UUID, target: TaskState) -> Task:
        task = self.get(task_id, for_update=True)
        current = TaskState(task.status)
        next_state = transition(current, target)
        task.status = next_state.value
        self.session.add(
            TaskAuditLog(
                tenant_id=self.session.tenant_id,
                task_id=task.id,
                actor=self.actor,
                from_status=current.value,
                to_status=next_state.value,
            )
        )
        self.session.flush()
        return task

    def fail(self, task_id: UUID, error: str) -> Task:
        task = self.advance(task_id, TaskState.FAILED)
        task.last_error = error
        self.session.flush()
        return task

    def audit_log(self, task_id: UUID) -> list[TaskAuditLog]:
        self.get(task_id)
        statement = (
            select(TaskAuditLog)
            .where(TaskAuditLog.task_id == task_id)
            .order_by(TaskAuditLog.occurred_at, TaskAuditLog.id)
        )
        return list(self.session.scalars(statement))


def completion_state(risk_level: RiskLevel) -> TaskState:
    if risk_level is RiskLevel.LOW:
        return TaskState.PUBLISHED
    return TaskState.AWAITING_REVIEW
